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

load_dotenv()
app = Flask(__name__, static_folder='static')
user_sessions = {}

REPORT_FLOW = {
    'awaiting_start':           { 'key': 'Inicio', 'next_state': 'awaiting_ot'},
    'awaiting_ot':              { 'key': 'O.T.', 'next_state': 'awaiting_fecha', 'question': '✅ Reportes iniciados. Ingrese la *O.T.*'},
    'awaiting_fecha':           { 'key': 'Fecha', 'next_state': 'awaiting_area', 'question': 'Ingrese la *Fecha* (DD/MM/YY).'},
    'awaiting_area':            { 'key': 'Area de trabajo', 'next_state': 'awaiting_lugar', 'question': 'Ingrese el *Área*.'},
    'awaiting_lugar':           { 'key': 'Lugar', 'next_state': 'awaiting_supervisor_persi', 'question': 'Ingrese el *Lugar*.'},
    'awaiting_supervisor_persi':{ 'key': 'Supervisor PERSI', 'next_state': 'awaiting_usuario_calidra', 'question': '¿Supervisor de PERSI?'},
    'awaiting_usuario_calidra': { 'key': 'Usuario Calidra', 'next_state': 'awaiting_trabajadores', 'question': '¿Usuario de Calidra?'},
    'awaiting_trabajadores':    { 'key': 'Trabajadores', 'next_state': 'awaiting_duracion', 'question': 'Nombres de *Trabajadores*.'},
    'awaiting_duracion':        { 'key': 'Duracion de trabajo', 'next_state': 'awaiting_general_description', 'question': '¿Duración del trabajo?'},
    'awaiting_general_description': { 'key': 'Descripcion general', 'next_state': 'awaiting_security_comments', 'question': 'Descripción general de la actividad.'},
    'awaiting_security_comments':   { 'key': 'Comentarios de seguridad', 'next_state': 'awaiting_partida_descripcion', 'question': 'Comentarios de seguridad.'},
    'awaiting_partida_descripcion': { 'key': 'descripcion', 'next_state': 'awaiting_partida_um', 'question': '➡️ Descripción de la partida.'},
    'awaiting_partida_um':        { 'key': 'um', 'next_state': 'awaiting_partida_cantidad', 'question': 'Unidad de Medida (U/M).'},
    'awaiting_partida_cantidad':  { 'key': 'cantidad', 'next_state': 'awaiting_partida_pu', 'question': 'Cantidad.'},
    'awaiting_partida_pu':        { 'key': 'pu', 'next_state': 'awaiting_next_partida', 'question': 'Precio Unitario (P/U).'},
    'awaiting_next_partida':      { 'key': 'Partida_Control', 'next_state': 'awaiting_fotos_antes', 'question': 'Partida agregada. ✅\n\n- Escriba *"agregar"* para otra.\n- Escriba *"listo"* para fotos.'},
    'awaiting_fotos_antes':     { 'key': 'Fotos_antes', 'next_state': 'awaiting_fotos_despues', 'question': 'Envíe hasta *2 fotos de ANTES*. Escriba "listo" al terminar.'},
    'awaiting_fotos_despues':   { 'key': 'Fotos_despues', 'next_state': 'report_complete', 'question': 'Envíe hasta *2 fotos de DESPUÉS*. Escriba "listo" para finalizar.'},
    'report_complete':          { 'key': 'Completo', 'next_state': 'report_complete', 'question': '¡Generando PDFs!'}
}

# --- FUNCIONES PDF (Sin cambios mayores, solo estabilidad) ---
def create_reporte1_pdf(report_data):
    template_path = "REPORTE1_3.pdf"
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=letter)
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
        can.drawString(38, y-10, str(i))
        can.drawString(345, y-10, str(p.get('um', '')))
        can.drawString(400, y-10, str(p.get('cantidad', '')))
        can.drawString(455, y-10, f"${float(p.get('pu',0)):,.2f}")
        can.drawString(507, y-10, f"${float(p.get('total',0)):,.2f}")
        para = Paragraph(str(p.get('descripcion', '')), getSampleStyleSheet()['Normal'])
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
    name = f'reporte_cotizacion_{uuid.uuid4()}.pdf'
    path = os.path.join(app.static_folder, 'reports', name)
    if not os.path.exists(os.path.dirname(path)): os.makedirs(os.path.dirname(path))
    with open(path, "wb") as f: output.write(f)
    return f"reports/{name}"

def create_reporte2_pdf(report_data, sid, token):
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
    para = Paragraph(report_data.get('Descripcion general', ''), getSampleStyleSheet()['Normal'])
    pw, ph = para.wrapOn(can, 520, 100)
    para.drawOn(can, 30, 687 - ph)
    def draw(paths, x, y_s, w, h):
        curr_y = y_s
        for p in paths:
            if os.path.exists(p):
                can.drawImage(p, x, curr_y - h, width=w, height=h)
                curr_y -= (h + 5)
    draw(report_data.get('Fotos_antes', []), 26, 545, 260, 156)
    draw(report_data.get('Fotos_despues', []), 294, 545, 274, 156)
    can.save()
    packet.seek(0)
    output = PdfWriter()
    template = PdfReader(open(template_path, "rb"))
    page = template.pages[0]
    page.merge_page(PdfReader(packet).pages[0])
    output.add_page(page)
    name = f'reporte_actividades_{uuid.uuid4()}.pdf'
    path = os.path.join(app.static_folder, 'reports', name)
    with open(path, "wb") as f: output.write(f)
    return f"reports/{name}"

# --- WEBHOOK WHATSAPP ---
@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    sender = request.values.get('From', '')
    msg = request.values.get('Body', '').strip()
    msg_l = msg.lower()
    num_media = int(request.values.get('NumMedia', 0))
    
    resp = MessagingResponse()
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")

    if sender not in user_sessions or 'iniciar' in msg_l:
        user_sessions[sender] = {'state': 'awaiting_ot', 'prev': None, 'data': {'Partidas': [], 'grand_total': 0.0}, 'part': {}}
        resp.message(REPORT_FLOW['awaiting_ot']['question'])
        return str(resp)

    session = user_sessions[sender]
    state = session['state']

    if msg_l == 'repetir' and session['prev']:
        session['state'] = session['prev']
        resp.message(f"Retrocediendo... {REPORT_FLOW[session['state']]['question']}")
        return str(resp)

    # MANEJO DE FOTOS
    if 'fotos' in state:
        key = REPORT_FLOW[state]['key']
        if key not in session['data']: session['data'][key] = []
        
        if num_media > 0:
            for i in range(num_media):
                if len(session['data'][key]) < 2:
                    url = request.values.get(f'MediaUrl{i}')
                    try:
                        r = requests.get(url, auth=(sid, token), timeout=30)
                        if r.status_code == 200:
                            if not os.path.exists('temp_images'): os.makedirs('temp_images')
                            path = f"temp_images/{uuid.uuid4()}.jpg"
                            with open(path, 'wb') as f: f.write(r.content)
                            session['data'][key].append(path)
                    except: pass
            
            count = len(session['data'][key])
            if count >= 2:
                resp.message(f"✅ Límite de 2 fotos alcanzado para {key.replace('_',' ')}.")
            else:
                resp.message(f"📸 Foto {count} de 2 recibida. Envíe otra o escriba 'listo'.")
            return str(resp)

        if 'listo' in msg_l:
            session['prev'] = state
            session['state'] = REPORT_FLOW[state]['next_state']
            if session['state'] == 'report_complete':
                try:
                    p1 = create_reporte1_pdf(session['data'])
                    p2 = create_reporte2_pdf(session['data'], sid, token)
                    resp.message("¡Generando tus reportes! 🚀")
                    resp.message().media(url_for('static', filename=p1, _external=True))
                    resp.message().media(url_for('static', filename=p2, _external=True))
                    # Limpieza
                    for f in session['data'].get('Fotos_antes',[]) + session['data'].get('Fotos_despues',[]):
                        if os.path.exists(f): os.remove(f)
                except Exception as e: resp.message(f"Error: {e}")
            else:
                resp.message(REPORT_FLOW[session['state']]['question'])
            return str(resp)
        return str(resp)

    # MANEJO DE PARTIDAS
    if 'partida' in state:
        if state == 'awaiting_next_partida':
            session['prev'] = state
            if 'listo' in msg_l: session['state'] = 'awaiting_fotos_antes'
            else: session['state'] = 'awaiting_partida_descripcion'
        else:
            session['part'][REPORT_FLOW[state]['key']] = msg
            next_s = REPORT_FLOW[state]['next_state']
            if next_s == 'awaiting_next_partida':
                try:
                    c, p = float(session['part'].get('cantidad',0)), float(session['part'].get('pu',0))
                    session['part']['total'] = c * p
                    session['data']['grand_total'] += session['part']['total']
                except: session['part']['total'] = 0
                session['data']['Partidas'].append(session['part'])
                session['part'] = {}
            session['prev'], session['state'] = state, next_s
        resp.message(REPORT_FLOW[session['state']]['question'])
        return str(resp)

    # FLUJO GENERAL
    session['data'][REPORT_FLOW[state]['key']] = msg
    session['prev'], session['state'] = state, REPORT_FLOW[state]['next_state']
    resp.message(REPORT_FLOW[session['state']]['question'])
    return str(resp)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5001)))