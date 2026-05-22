import streamlit as st
import pandas as pd
import pyrebase
import firebase_admin
from firebase_admin import credentials, firestore
import json
import re
from datetime import datetime

# --- CONFIGURACIÓN ---
with open('config.json') as f:
    config = json.load(f)

firebase = pyrebase.initialize_app(config)
auth = firebase.auth()

if not firebase_admin._apps:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --- FUNCIONES ---
def obtener_rol(email):
    doc = db.collection('usuarios').document(email).get()
    return doc.to_dict().get('rol') if doc.exists else "consultor"

def validar_campos_estrictos(placa, vin):
    if not placa or not vin:
        st.warning("⚠️ Debes ingresar Placa y VIN.")
        return False
    return True

# --- INTERFAZ ---
st.set_page_config(page_title="Portal RTV Piñas", layout="wide")
st.title("🚗 Portal RTV Piñas")

if "rol" not in st.session_state: st.session_state.rol = "invitado"

# --- LOGIN PROFESIONAL ---
if st.session_state.rol == "invitado":
    with st.sidebar:
        st.subheader("Acceso Administrativo")
        email_in = st.text_input("Correo")
        pwd_in = st.text_input("Contraseña", type="password")
        if st.button("Entrar"):
            try:
                # Valida contra Firebase Auth (Google)
                user = auth.sign_in_with_email_and_password(email_in, pwd_in)
                st.session_state.rol = obtener_rol(email_in)
                st.session_state.user = email_in
                st.rerun()
            except:
                st.error("Correo o contraseña incorrectos.")
else:
    with st.sidebar:
        st.write(f"👤 {st.session_state.user}")
        if st.button("Cerrar Sesión"):
            st.session_state.clear()
            st.rerun()

# --- ESTRUCTURA DE TABS ---
if st.session_state.rol == "admin":
    tabs = st.tabs(["Consulta", "Administración", "Gestión de Usuarios"])
elif st.session_state.rol == "admin_archivo":
    tabs = st.tabs(["Consulta", "Administración"])
else:
    tabs = [st.tabs(["Consulta"])[0]]

# --- TAB 1: CONSULTA ---
with tabs[0]:
    col_a, col_b = st.columns(2)
    placa = col_a.text_input("Placa")
    vin = col_b.text_input("VIN / Chasis")
    
    if st.button("Consultar"):
        if validar_campos_estrictos(placa, vin):
            query = db.collection('inspecciones').where('VEHICULO', '==', placa.upper()).where('VIN', '==', vin.upper())
            res = [doc.to_dict() for doc in query.stream()]
            
            if res:
                st.markdown("---")
                st.markdown("### 📋 Resultados de la Inspección")
                for r in res:
                    st.info(f"**Vehículo:** {r.get('MARCA', 'N/A')} {r.get('MODELO', 'N/A')} | **Placa:** {r.get('VEHICULO', 'N/A')}")
                    
                    # Colores dinámicos según el resultado
                    resultado = r.get('RESULTADO TECNICO', 'N/A')
                    if "Aproba" in resultado:
                        st.success(f"**Estado:** {resultado}")
                    elif "Condicion" in resultado:
                        st.warning(f"**Estado:** {resultado}")
                    else:
                        st.error(f"**Estado:** {resultado}")
            else: 
                st.info("No se encontraron registros para los datos ingresados.")

# --- TAB 2: ADMINISTRACIÓN ---
# --- TAB 2: ADMINISTRACIÓN ---
if len(tabs) > 1:
    with tabs[1]:
        st.subheader("Subir Nueva Base de Datos")
        file = st.file_uploader("Seleccione el archivo CSV", type="csv")
        
        if file and st.button("Cargar datos"):
            # Leer el archivo (recuerda ajustar o quitar el skiprows=1 según limpiaste tu Excel)
            df = pd.read_csv(file, sep=';', encoding='latin1', skiprows=1) 
            batch = db.batch()
            
            # 1. Guardar los vehículos
            for r in df.to_dict('records'): 
                vin_id = str(r.get('VIN')).strip()
                doc_ref = db.collection('inspecciones').document(vin_id) if vin_id and vin_id.lower() != 'nan' else db.collection('inspecciones').document()
                batch.set(doc_ref, r, merge=True)
                
            batch.commit()
            
            # 2. GUARDAR EL REGISTRO DE QUIÉN SUBIÓ EL ARCHIVO (Auditoría)
            registro_auditoria = {
                'fecha_hora': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'usuario': st.session_state.user,
                'nombre_archivo': file.name,
                'cantidad_vehiculos': len(df)
            }
            db.collection('historial_cargas').add(registro_auditoria)
            
            st.success("✅ Registros cargados y guardados en el historial de auditoría.")

        # --- MOSTRAR EL HISTORIAL SOLO AL ADMIN ---
        st.markdown("---")
        st.subheader("🕒 Historial de Archivos Subidos")
        
        # Leer el historial desde Firebase, ordenado por fecha (el más nuevo primero)
        historial_query = db.collection('historial_cargas').order_by('fecha_hora', direction=firestore.Query.DESCENDING).limit(10)
        historial_datos = [doc.to_dict() for doc in historial_query.stream()]
        
        if historial_datos:
            # Mostramos el historial en una tabla bonita de Pandas
            df_historial = pd.DataFrame(historial_datos)
            st.dataframe(df_historial, use_container_width=True)
        else:
            st.info("Aún no hay registros de archivos subidos.")

# --- TAB 3: GESTIÓN (SOLO SUPER ADMIN) ---
if len(tabs) > 2:
    with tabs[2]:
        new_mail = st.text_input("Email a registrar")
        new_role = st.selectbox("Rol", ["admin_archivo", "consultor"])
        if st.button("Asignar"):
            db.collection('usuarios').document(new_mail).set({'rol': new_role})
            st.success("Usuario asignado.")
