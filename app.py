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

# --- INICIALIZACIÓN SEGURA DE FIREBASE ADMIN ---
try:
    # Intenta usar la conexión si ya existe en la memoria de Streamlit
    firebase_admin.get_app()
except ValueError:
    # Si no existe, entonces la crea por primera vez
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
    
    # Validar caracteres (letras, números y guión para placa)
    if not re.match(r"^[a-zA-Z0-9\-]+$", placa):
        st.error("⚠️ La Placa contiene caracteres inválidos. Usa solo letras y números.")
        return False
        
    # Validar que el VIN solo contenga letras y números
    if not re.match(r"^[a-zA-Z0-9]+$", vin):
        st.error("⚠️ El VIN/Chasis contiene caracteres inválidos. Usa solo letras y números.")
        return False
        
    return True

# --- INTERFAZ ---
st.set_page_config(page_title="Portal RTV Piñas", layout="wide")
st.title("🚗 Portal RTV Piñas")

if "rol" not in st.session_state: st.session_state.rol = "invitado"

# --- LOGIN PROFESIONAL CON VALIDACIÓN ---
if st.session_state.rol == "invitado":
    with st.sidebar:
        st.subheader("Acceso Administrativo")
        email_in = st.text_input("Correo")
        pwd_in = st.text_input("Contraseña", type="password")
        
        if st.button("Entrar"):
            # 1. Validar que el formato del correo sea correcto (ejemplo@dominio.com)
            es_correo_valido = re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", email_in)
            
            if not email_in or not pwd_in:
                st.error("⚠️ Debes ingresar correo y contraseña.")
            elif not es_correo_valido:
                st.error("⚠️ Formato de correo inválido. Revisa que no haya espacios o letras incorrectas.")
            elif len(pwd_in) < 6:
                st.error("⚠️ La contraseña debe tener al menos 6 caracteres.")
            else:
                try:
                    # Valida contra Firebase Auth (Google)
                    user = auth.sign_in_with_email_and_password(email_in, pwd_in)
                    st.session_state.rol = obtener_rol(email_in)
                    st.session_state.user = email_in
                    st.rerun()
                except:
                    st.error("❌ Correo o contraseña incorrectos. Intenta de nuevo.")
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
    
    # Límite físico y conversión automática a mayúsculas
    placa = col_a.text_input("Placa", max_chars=8).upper()
    vin = col_b.text_input("VIN / Chasis", max_chars=17).upper()
    
    if st.button("Consultar"):
        if validar_campos_estrictos(placa, vin):
            query = db.collection('inspecciones').where('VEHICULO', '==', placa).where('VIN', '==', vin)
            res = [doc.to_dict() for doc in query.stream()]
            
            if res:
                st.markdown("---")
                st.markdown("### 📋 Resultados de la Inspección")
                for r in res:
                    fecha_mostrar = r.get('FECHA', r.get('fecha', r.get('FECHA_DE_CARGA', 'No disponible')))
                    
                    st.info(
                        f"**Vehículo:** {r.get('MARCA', 'N/A')} {r.get('MODELO', '')} | "
                        f"**Placa:** {r.get('VEHICULO', 'N/A')} \n\n"
                        f"📅 **Fecha de Revisión:** {fecha_mostrar}"
                    )
                    
                    resultado = str(r.get('RESULTADO TECNICO', 'N/A'))
                    if "Aproba" in resultado:
                        st.success(f"**Estado:** {resultado}")
                    elif "Condicion" in resultado:
                        st.warning(f"**Estado:** {resultado}")
                    else:
                        st.error(f"**Estado:** {resultado}")
            else: 
                st.info("No se encontraron registros para los datos ingresados.")

# --- TAB 2: ADMINISTRACIÓN ---
if len(tabs) > 1:
    with tabs[1]:
        st.subheader("Subir Nueva Base de Datos")
        file = st.file_uploader("Seleccione el archivo CSV", type="csv")
        
        if file and st.button("Cargar datos"):
            df = pd.read_csv(file, sep=';', encoding='latin1') # Asegúrate de tener tu CSV limpio en la primera fila
            batch = db.batch()
            
            for r in df.to_dict('records'): 
                # Estampilla la fecha de carga del sistema
                r['FECHA_DE_CARGA'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                r['USUARIO_ADMIN'] = st.session_state.user
                
                vin_id = str(r.get('VIN')).strip()
                doc_ref = db.collection('inspecciones').document(vin_id) if vin_id and vin_id.lower() != 'nan' else db.collection('inspecciones').document()
                batch.set(doc_ref, r, merge=True)
                
            batch.commit()
            
            # Guardar auditoría
            registro_auditoria = {
                'fecha_hora': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'usuario': st.session_state.user,
                'nombre_archivo': file.name,
                'cantidad_vehiculos': len(df)
            }
            db.collection('historial_cargas').add(registro_auditoria)
            
            st.success("✅ Registros cargados y actualizados correctamente.")

        # Historial de auditoría
        st.markdown("---")
        st.subheader("🕒 Historial de Archivos Subidos")
        
        historial_query = db.collection('historial_cargas').order_by('fecha_hora', direction=firestore.Query.DESCENDING).limit(10)
        historial_datos = [doc.to_dict() for doc in historial_query.stream()]
        
        if historial_datos:
            df_historial = pd.DataFrame(historial_datos)
            df_historial.rename(columns={
                'fecha_hora': 'Fecha de Carga', 
                'usuario': 'Usuario', 
                'nombre_archivo': 'Archivo', 
                'cantidad_vehiculos': 'Total Registros'
            }, inplace=True)
            st.dataframe(df_historial, use_container_width=True)
        else:
            st.info("Aún no hay registros de archivos subidos.")

# --- TAB 3: GESTIÓN (SOLO SUPER ADMIN) ---
if len(tabs) > 2:
    with tabs[2]:
        new_mail = st.text_input("Email a registrar")
        new_role = st.selectbox("Rol", ["admin_archivo", "consultor"])
        if st.button("Asignar"):
            # Validación rápida para el correo nuevo también
            if re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", new_mail):
                db.collection('usuarios').document(new_mail).set({'rol': new_role})
                st.success(f"✅ Usuario {new_mail} asignado correctamente.")
            else:
                st.error("⚠️ Ingresa un formato de correo válido antes de asignar.")
