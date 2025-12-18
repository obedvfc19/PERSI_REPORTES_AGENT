import os
import requests
import uuid
import io
from flask import Flask, request, url_for
from twilio.twiml.messaging_response import MessagingResponse
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.platypus import Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from dotenv import load_dotenv

# --- 0. INICIALIZACIÓN ---
load_dotenv()
app = Flask(__name__, static_folder='static')
user_sessions = {}

# --- 1. GUION DE LA CONVERSACIÓN ---
REPORT_FLOW = {
    'awaiting_start':           { 'key': 'Inicio', 'next_state': 'awaiting_ot'},
    'awaiting_ot':              { 'key': 'O.T.', 'next_state': 'awaiting_fecha', 'question': '✅ Reportes iniciados. Por favor, ingresa la *O.T. (Orden de Trabajo)*.'},
    'awaiting_fecha':           { 'key': 'Fecha', 'next_state': 'awaiting_area', 'question': 'Ahora, por favor, escribe la *Fecha* en formato DD/MM/YY.'},
    'awaiting_area':            { 'key': 'Area de trabajo', 'next_state': 'awaiting_lugar', 'question': 'Ingresa el *Área* de trabajo.'},
    'awaiting_lugar':           { 'key': 'Lugar', 'next_state': 'awaiting_supervisor_persi', 'question': 'Gracias. Ahora, escribe el *Lugar* específico.'},
    'awaiting_supervisor_persi':{ 'key': 'Supervisor PERSI', 'next_state': 'awaiting_usuario_calidra', 'question': '¿Quién es el *Supervisor de PERSI*?'},
    'awaiting_usuario_calidra': { 'key': 'Usuario Calidra', 'next_state': 'awaiting_trabajadores', 'question': '¿Y el *Usuario*?'},
    'awaiting_trabajadores':    { 'key': 'Trabajadores', 'next_state': 'awaiting_duracion', 'question': 'Anotado. Escribe los nombres de los *Trabajadores* que intervienen.'},
    'awaiting_duracion':        { 'key': 'Duracion de trabajo', 'next_state': 'awaiting_general_description', 'question': 'Perfecto. Ahora, especifica la *Duración del trabajo* (ej: 8 horas).'},
    'awaiting_general_description': { 'key': 'Descripcion general', 'next_state': 'awaiting_security_comments', 'question': 'Ahora, ingresa una *descripción general de la actividad*.'},
    'awaiting_security_comments':   { 'key': 'Comentarios de seguridad', 'next_state': 'awaiting_partida_descripcion', 'question': 'Gracias. Ahora añade los *comentarios de seguridad*.'},
    'awaiting_partida_descripcion': { 'key': 'descripcion', 'next_state': 'awaiting_partida_um', 'question': '➡️ Ingrese la *descripción de la actividad* para la partida.'},
    'awaiting_partida_um':        { 'key': 'um', 'next_state': 'awaiting_partida_cantidad', 'question': 'Ingrese la *Unidad de Medida (U/M)*.'},
    'awaiting_partida_cantidad':  { 'key': 'cantidad', 'next_state': 'awaiting_partida_pu', 'question': 'Ingrese la *cantidad*.'},
    'awaiting_partida_pu':        { 'key': 'pu', 'next_state': 'awaiting_next_partida', 'question': 'Ingrese el *Precio Unitario (P/U)*.'},
    'awaiting_next_partida':      { 'key': 'Partida_Control', 'next_state': 'awaiting_fotos_antes', 'question': 'Partida agregada. ✅\n\n- Escriba *"agregar"* para otra partida.\n- Escriba *"listo"* para continuar.'},
    'awaiting_fotos_antes':     { 'key': 'Fotos_antes', 'next_state': 'awaiting_fotos_despues', 'question': 'Envíe hasta *2 fotos de ANTES*. Al terminar, escriba "listo".'},
    'awaiting_fotos_despues':   { 'key': 'Fotos_despues', 'next_state': 'report_complete', 'question': 'Ahora, envíe hasta *2 fotos de DESPUÉS*. Al terminar, escriba "listo".'},
    'report_complete':          { 'key': 'Completo', 'next_state': 'report_complete', 'question': '¡Generando PDFs! Espere un momento...'}
}

# --- 2. FUNCIONES DE PDF ---
def create_reporte1_pdf(report_data):
    template_path = "REPORTE1_3.pdf"
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=letter)
    styles = getSampleStyleSheet()
    style_normal = styles['Normal']
    style_normal.fontSize = 8
    can.setFont("Helvetica", 9)
    can.drawString(95, 723, str(report_data.get('Area de trabajo', '')))
    can.drawString(60, 711, str(report_data.get('Lugar', '')))
    can.drawString(400, 723, str(report_data.get('Fecha', '')))
    can.drawString(360, 711, str(report_data.get('O.T.', '')))
    can.drawString(415, 686, str(report_data.get('Supervisor PERSI', '')))
    can.drawString(405, 698, str(report_data.get('Usuario Calidra', '')))
    can.drawString(28, 690, str(report_data.get('Trabajadores', '')))
    can.drawString(535, 711, str(report_data.get('Duracion de trabajo', '')))
    y = 663
    for i, p in enumerate(report_data.get('Partidas', []), 1):
        can.drawString(38, y - 10, str(i))
        can.drawString(345, y - 10, str(p.get('um', '')))
        can.drawString(400, y - 10, str(p.get('cantidad', '')))
        can.drawString(455, y - 10, f"${float(p.get('pu',0)):,.2f}")
        can.drawString(507, y - 10, f"${float(p.get('total',0)):,.2f}")
        para = Paragraph(str(p.get('descripcion', '')), style_normal)
        pw, ph = para.wrapOn(can, 250, 74)
        para.drawOn(can, 70, y - ph - 5)
        y -= 74
    can.setFont("Helvetica-Bold", 10)
    can.drawString(507, 213, f"${report_data.get('grand_total', 0):,.2f}")
    can.save()
    packet.seek(0)
    output = PdfWriter()
    template = PdfReader(open(template_path, "rb"))
    page = template.pages[0]
    page.merge_page(PdfReader(packet).pages[0])
    output.add_page(page)
    if not os.path.exists('static/reports'): os.makedirs('static/reports')
    name = f'reporte_cotizacion_{uuid.uuid4()}.pdf'
    with open(os.path.join(app.static_folder, 'reports', name), "wb") as f: output.write(f)
    return os.path.join('reports', name).replace('\\', '/')

def create_reporte2_pdf(report_data, account_sid, auth_token):
    template_path = "REPORTE2.pdf"
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=letter)
    can.setFont("Helvetica", 9)
    can.drawString(92, 755, str(report_data.get('Area de trabajo', '')))
    can.drawString(55, 743, str(report_data.get('Lugar', '')))
    can.drawString(370, 755, str(report_data.get('Fecha', '')))
    can.drawString(318, 743, str(report_data.get('O.T.', '')))
    can.drawString(365, 718, str(report_data.get('Supervisor PERSI', '')))
    can.drawString(365, 730, str(report_data.get('Usuario Calidra', '')))
    can.drawString(25, 722, str(report_data.get('Trabajadores', '')))
    can.drawString(508, 743, str(report_data.get('Duracion de trabajo', '')))
    desc = Paragraph(report_data.get('Descripcion general', ''), getSampleStyleSheet()['Normal'])
    dw, dh = desc.wrapOn(can, 520, 100)
    desc.drawOn(can, 30, 687 - dh)
    def draw_imgs(paths, x, y_start, w, h):
        curr_y = y_start
        for p in paths:
            if os.path.exists(p):
                can.drawImage(p, x, curr_y - h, width=w, height=h)
                curr_y -= (h + 5)
    draw_imgs(report_data.get('Fotos_antes', []), 26, 545, 260, 156)
    draw_imgs(report_data.get('Fotos_despues', []), 294, 545, 274, 156)
    can.save()
    packet.seek(0)
    output = PdfWriter()
    template = PdfReader(open(template_path, "rb"))
    page = template.pages[0]
    page.merge_page(PdfReader(packet).pages[0])
    output.add_page(page)
    name = f'reporte_actividades_{uuid.uuid4()}.pdf'
    with open(os.path.join(app.static_folder, 'reports', name), "wb") as f: output.write(f)
    return os.path.join('reports', name).replace('\\', '/')

# --- 3. WEBHOOK WHATSAPP ---
@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    sender_id = request.values.get('From', '')
    incoming_msg = request.values.get('Body', '').strip()
    incoming_lower = incoming_msg.lower()
    num_media = int(request.values.get('NumMedia', 0))
    media_urls = [request.values.get(f'MediaUrl{i}') for i in range(num_media)]
    
    resp = MessagingResponse()
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")

    # Iniciar/Reiniciar
    if sender_id not in user_sessions or 'iniciar' in incoming_lower:
        user_sessions[sender_id] = {
            'state': 'awaiting_ot', 
            'previous_state': None,
            'report_data': {'Partidas': [], 'grand_total': 0.0},
            'current_partida': {}
        }
        resp.message(REPORT_FLOW['awaiting_ot']['question'])
        return str(resp)

    session = user_sessions[sender_id]
    state = session['state']

    # Función Repetir
    if incoming_lower == 'repetir':
        if session.get('previous_state'):
            session['state'] = session['previous_state']
            resp.message(f"Ok, volvamos atrás. {REPORT_FLOW[session['state']]['question']}")
        else:
            resp.message(REPORT_FLOW[state]['question'])
        return str(resp)

    # Lógica de Fotos
    if 'fotos' in state:
        key = REPORT_FLOW[state]['key']
        if key not in session['report_data']: session['report_data'][key] = []
        if num_media > 0:
            exito = False
            for url in media_urls:
                if len(session['report_data'][key]) < 2:
                    try:
                        r = requests.get(url, auth=(sid, token), timeout=30)
                        if r.status_code == 200:
                            if not os.path.exists('temp_images'): os.makedirs('temp_images')
                            path = os.path.join('temp_images', f"{uuid.uuid4()}.jpg")
                            with open(path, 'wb') as f: f.write(r.content)
                            session['report_data'][key].append(path)
                            exito = True
                    except Exception as e: print(f"Error: {e}")
            if exito:
                count = len(session['report_data'][key])
                if count >= 2:
                    resp.message("✅ Límite alcanzado.")
                    session['previous_state'] = state
                    session['state'] = REPORT_FLOW[state]['next_state']
                    resp.message(REPORT_FLOW[session['state']]['question'])
                else:
                    resp.message(f"📸 Foto {count} de 2 recibida. Envíe otra o escriba 'listo'.")
            return str(resp)
        if 'listo' in incoming_lower:
            session['previous_state'] = state
            session['state'] = REPORT_FLOW[state]['next_state']
            if session['state'] == 'report_complete':
                try:
                    p1 = create_reporte1_pdf(session['report_data'])
                    p2 = create_reporte2_pdf(session['report_data'], sid, token)
                    resp.message("¡Reportes listos! 👇")
                    resp.message().media(url_for('static', filename=p1, _external=True))
                    resp.message().media(url_for('static', filename=p2, _external=True))
                    for f in session['report_data'].get('Fotos_antes', []) + session['report_data'].get('Fotos_despues', []):
                        if os.path.exists(f): os.remove(f)
                except Exception as e: resp.message(f"Error: {e}")
            else:
                resp.message(REPORT_FLOW[session['state']]['question'])
            return str(resp)
        resp.message("Envíe foto o escriba 'listo'.")
        return str(resp)

    # Lógica de Partidas
    if 'partida' in state:
        if state == 'awaiting_next_partida':
            session['previous_state'] = state
            if 'listo' in incoming_lower: session['state'] = 'awaiting_fotos_antes'
            else: session['state'] = 'awaiting_partida_descripcion'
            resp.message(REPORT_FLOW[session['state']]['question'])
        else:
            key = REPORT_FLOW[state]['key']
            session['current_partida'][key] = incoming_msg
            next_st = REPORT_FLOW[state]['next_state']
            if next_st == 'awaiting_next_partida':
                try:
                    cant, pu = float(session['current_partida'].get('cantidad', 0)), float(session['current_partida'].get('pu', 0))
                    session['current_partida']['total'] = cant * pu
                    session['report_data']['grand_total'] += session['current_partida']['total']
                except: session['current_partida']['total'] = 0
                session['report_data']['Partidas'].append(session['current_partida'])
                session['current_partida'] = {}
            session['previous_state'], session['state'] = state, next_st
            resp.message(REPORT_FLOW[next_st]['question'])
        return str(resp)

    # Flujo General
    key = REPORT_FLOW[state]['key']
    session['report_data'][key] = incoming_msg
    session['previous_state'], session['state'] = state, REPORT_FLOW[state]['next_state']
    resp.message(REPORT_FLOW[session['state']]['question'])
    return str(resp)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5001)))