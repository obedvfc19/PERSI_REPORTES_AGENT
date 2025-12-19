import os
import requests
import uuid
import io
import random
from flask import Flask, request, url_for
from twilio.twiml.messaging_response import MessagingResponse
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.platypus import Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from dotenv import load_dotenv

# --- 0. INICIALIZACIÓN Y CARGA DE CREDENCIALES ---
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
    'awaiting_general_description': { 'key': 'Descripcion general', 'next_state': 'awaiting_security_comments', 'question': 'Ahora, ingresa una *descripción general de la actividad* (esto irá en el Reporte de Actividades).'},
    'awaiting_security_comments':   { 'key': 'Comentarios de seguridad', 'next_state': 'awaiting_partida_descripcion', 'question': 'Gracias. Ahora añade los *comentarios de seguridad* (esto irá en el reporte de Cotización).'},
    'awaiting_partida_descripcion': { 'key': 'descripcion', 'next_state': 'awaiting_partida_um', 'question': '➡️ Ingrese la *descripción de la actividad* para la partida actual.'},
    'awaiting_partida_um':        { 'key': 'um', 'next_state': 'awaiting_partida_cantidad', 'question': 'Ahora ingrese la *Unidad de Medida (U/M)* (p. ej., pza, m, kg).'},
    'awaiting_partida_cantidad':  { 'key': 'cantidad', 'next_state': 'awaiting_partida_pu', 'question': 'Ingrese la *cantidad*.'},
    'awaiting_partida_pu':        { 'key': 'pu', 'next_state': 'awaiting_next_partida', 'question': 'Ahora ingrese el *Precio Unitario (P/U)*.'},
    'awaiting_next_partida':      { 'key': 'Partida_Control', 'next_state': 'awaiting_fotos_antes', 'question': 'Partida agregada. ✅\n\n- Escriba *"agregar"* para añadir otra partida.\n- Escriba *"listo"* para continuar con el reporte.'},
    'awaiting_fotos_antes':     { 'key': 'Fotos_antes', 'next_state': 'awaiting_fotos_despues', 'question': 'Vamos con las fotos. Envía hasta *2 fotos de ANTES*. Cuando termines, escribe "listo".'},
    'awaiting_fotos_despues':   { 'key': 'Fotos_despues', 'next_state': 'report_complete', 'question': 'Fotos de "antes" recibidas. ✅ Ahora, envía hasta *2 fotos de DESPUÉS*. Cuando termines, escribe "listo".'},
    'report_complete':          { 'key': 'Completo', 'next_state': 'report_complete', 'question': '¡Reportes completados! ✅ Estoy generando tus PDFs, por favor espera un momento...'}
}

## Funciones de Creación de PDF

def create_reporte1_pdf(report_data):
    template_path = "REPORTE1_3.pdf"
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=letter)
    
    styles = getSampleStyleSheet()
    style_normal = styles['Normal']
    style_normal.fontName = 'Helvetica'
    style_normal.fontSize = 8
    style_normal.leading = 10 

    # --- Dibuja todo el contenido en el canvas ---
    can.setFont("Helvetica", 9)
    can.drawString(95, 723, str(report_data.get('Area de trabajo', '')))
    can.drawString(60, 711, str(report_data.get('Lugar', '')))
    can.drawString(400, 723, str(report_data.get('Fecha', '')))
    can.drawString(360, 711, str(report_data.get('O.T.', '')))
    can.drawString(415, 686, str(report_data.get('Supervisor PERSI', '')))
    can.drawString(405, 698, str(report_data.get('Usuario Calidra', '')))
    can.drawString(28, 690, str(report_data.get('Trabajadores', '')))
    can.drawString(535, 711, str(report_data.get('Duracion de trabajo', '')))

    initial_y_position = 663
    cell_height = 74
    item_count = 1

    for partida in report_data.get('Partidas', []):
        y_position = initial_y_position - ((item_count - 1) * cell_height)
        
        can.setFont("Helvetica", 9)
        can.drawString(38, y_position - 10, str(item_count))
        can.drawString(345, y_position - 10, str(partida.get('um', '')))
        can.drawString(400, y_position - 10, str(partida.get('cantidad', '')))
        try:
            pu_val = float(partida.get('pu', 0))
            total_val = float(partida.get('total', 0))
        except (ValueError, TypeError):
            pu_val = 0
            total_val = 0
        can.drawString(455, y_position - 10, f"${pu_val:,.2f}")
        can.drawString(507, y_position - 10, f"${total_val:,.2f}")

        descripcion_text = str(partida.get('descripcion', ''))
        max_width = 250
        p = Paragraph(descripcion_text, style_normal)
        
        p_width, p_height = p.wrapOn(can, max_width, cell_height)
        p.drawOn(can, 70, y_position - p_height - 5)
        
        item_count += 1
    
    grand_total = report_data.get('grand_total', 0)
    can.setFont("Helvetica-Bold", 10)
    can.drawString(507, 213, f"${grand_total:,.2f}")
    
    comments = report_data.get('Comentarios de seguridad', '')
    style_comments = styles['Normal']
    style_comments.fontName = 'Helvetica'
    style_comments.fontSize = 9
    style_comments.leading = 11
    
    p_comments = Paragraph(comments, style_comments)
    p_comments_width, p_comments_height = p_comments.wrapOn(can, 540, 60)
    p_comments.drawOn(can, 35, 195 - p_comments_height)

    can.save()
    packet.seek(0)
    
    # --- Lógica de fusión y guardado ---
    new_pdf_content = PdfReader(packet)
    existing_pdf_template = PdfReader(open(template_path, "rb"))
    output = PdfWriter()
    
    page = existing_pdf_template.pages[0]
    page.merge_page(new_pdf_content.pages[0])
    
    # ✅ LÍNEA CORREGIDA: Se añade la página al archivo final
    output.add_page(page)
    
    if not os.path.exists('static/reports'): os.makedirs('static/reports')
    pdf_filename = f'reporte_cotizacion_{uuid.uuid4()}.pdf'
    pdf_path = os.path.join(app.static_folder, 'reports', pdf_filename)
    with open(pdf_path, "wb") as outputStream:
        output.write(outputStream)
    return os.path.join('reports', pdf_filename).replace('\\', '/')

def create_reporte2_pdf(report_data, account_sid, auth_token):
    template_path = "REPORTE2.pdf"
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=letter)
    
    styles = getSampleStyleSheet()
    style_desc = styles['Normal']
    style_desc.fontName = 'Helvetica'
    style_desc.fontSize = 9
    style_desc.leading = 11

    # --- Dibuja todo el contenido en el canvas ---
    can.setFont("Helvetica", 9)
    can.drawString(92, 755, str(report_data.get('Area de trabajo', '')))
    can.drawString(55, 743, str(report_data.get('Lugar', '')))
    can.drawString(370, 755, str(report_data.get('Fecha', '')))
    can.drawString(318, 743, str(report_data.get('O.T.', '')))
    can.drawString(365, 718, str(report_data.get('Supervisor PERSI', '')))
    can.drawString(365, 730, str(report_data.get('Usuario Calidra', '')))
    can.drawString(25, 722, str(report_data.get('Trabajadores', '')))
    can.drawString(508, 743, str(report_data.get('Duracion de trabajo', '')))

    description = report_data.get('Descripcion general', '')
    p_desc = Paragraph(description, style_desc)
    
    p_desc_width, p_desc_height = p_desc.wrapOn(can, 520, 100)
    p_desc.drawOn(can, 30, 687 - p_desc_height)
    
    def add_image_gallery(image_paths, x_start, y_top, image_width, image_height):
        y_cursor = y_top
        for path in image_paths:
            try:
                can.drawImage(path, x_start, y_cursor - image_height, width=image_width, height=image_height, mask='auto', preserveAspectRatio=False)
            except Exception as e:
                print(f"!!! ERROR al dibujar la imagen {path}: {e}")
            y_cursor -= (image_height + 5)

    if not os.path.exists('temp_images'): os.makedirs('temp_images')
    add_image_gallery(report_data.get('Fotos_antes', []), x_start=26, y_top=545, image_width=260, image_height=156)
    add_image_gallery(report_data.get('Fotos_despues', []), x_start=294, y_top=545, image_width=274, image_height=156)

    can.save()
    packet.seek(0)

    # --- Lógica de fusión y guardado ---
    new_pdf_content = PdfReader(packet)
    existing_pdf_template = PdfReader(open(template_path, "rb"))
    output = PdfWriter()

    page = existing_pdf_template.pages[0]
    page.merge_page(new_pdf_content.pages[0])
    
    # ✅ LÍNEA CORREGIDA: Se añade la página al archivo final
    output.add_page(page)

    if not os.path.exists('static/reports'): os.makedirs('static/reports')
    pdf_filename = f'reporte_actividades_{uuid.uuid4()}.pdf'
    pdf_path = os.path.join(app.static_folder, 'reports', pdf_filename)
    with open(pdf_path, "wb") as outputStream:
        output.write(outputStream)
    return os.path.join('reports', pdf_filename).replace('\\', '/')


@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    sender_id = request.values.get('From', '')
    incoming_msg_original = request.values.get('Body', '').strip()
    incoming_msg_lower = incoming_msg_original.lower()
    media_urls = [request.values.get(f'MediaUrl{i}') for i in range(int(request.values.get('NumMedia', 0)))]
    resp = MessagingResponse()
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    MAX_PHOTOS = 2

    if incoming_msg_lower == 'repetir':
        if sender_id in user_sessions:
            session = user_sessions[sender_id]
            previous_state = session.get('previous_state')
            if previous_state:
                session['state'] = previous_state
                question = REPORT_FLOW[previous_state].get('question')
                if question:
                    resp.message("Ok, volvamos un paso atrás.")
                    resp.message(question)
            else:
                current_state = session['state']
                question = REPORT_FLOW[current_state].get('question')
                if question:
                    resp.message(question)
        return str(resp)

    if sender_id not in user_sessions or 'iniciar' in incoming_msg_lower:
        user_sessions[sender_id] = {
            'state': 'awaiting_start',
            'previous_state': None,
            'report_data': {'Partidas': [], 'grand_total': 0.0},
            'current_partida': {}
        }

    session = user_sessions[sender_id]
    current_state = session['state']
    flow_step = REPORT_FLOW[current_state]

    def advance_state(session, current_state, next_state_key):
        session['previous_state'] = current_state
        session['state'] = next_state_key
        return REPORT_FLOW[next_state_key].get('question')

    if 'partida' in current_state:
        if current_state == 'awaiting_next_partida':
            if 'listo' in incoming_msg_lower:
                question = advance_state(session, current_state, flow_step['next_state'])
                resp.message(question)
            else:
                question = advance_state(session, current_state, 'awaiting_partida_descripcion')
                num_partida = len(session['report_data']['Partidas']) + 1
                resp.message(f"Ok, vamos con la partida #{num_partida}.")
                resp.message(question)
        else:
            session['current_partida'][flow_step['key']] = incoming_msg_original
            next_state_key = flow_step['next_state']
            if next_state_key == 'awaiting_next_partida':
                try:
                    cantidad = float(session['current_partida'].get('cantidad', 0))
                    pu = float(session['current_partida'].get('pu', 0))
                    total_partida = cantidad * pu
                    session['current_partida']['total'] = total_partida
                    session['report_data']['grand_total'] += total_partida
                except (ValueError, TypeError):
                    session['current_partida']['total'] = 0
                session['report_data']['Partidas'].append(session['current_partida'])
                session['current_partida'] = {}
            question = advance_state(session, current_state, next_state_key)
            resp.message(question)

    elif 'fotos' in current_state:
        photo_key = flow_step['key']
        if photo_key not in session['report_data']:
            session['report_data'][photo_key] = []
        current_photo_count = len(session['report_data'][photo_key])
        if media_urls:
            if current_photo_count < MAX_PHOTOS:
                if not os.path.exists('temp_images'):
                    os.makedirs('temp_images')
                for url in media_urls:
                    if len(session['report_data'][photo_key]) < MAX_PHOTOS:
                        try:
                            response = requests.get(url, auth=(account_sid, auth_token), timeout=30)
                            if response.status_code == 200:
                                temp_filename = f"{uuid.uuid4()}.jpg"
                                temp_path = os.path.join('temp_images', temp_filename)
                                with open(temp_path, 'wb') as f:
                                    f.write(response.content)
                                session['report_data'][photo_key].append(temp_path)
                        except Exception as e:
                            print(f"¡EXCEPCIÓN al descargar imagen {url}: {e}")
                new_photo_count = len(session['report_data'][photo_key])
                if new_photo_count >= MAX_PHOTOS:
                    resp.message(f"Límite de {MAX_PHOTOS} fotos alcanzado. ✅")
                    question = advance_state(session, current_state, flow_step['next_state'])
                    if question: resp.message(question)
                else:
                    resp.message(f"Foto {new_photo_count} de {MAX_PHOTOS} recibida. Envía otra o escribe 'listo'.")
        elif 'listo' in incoming_msg_lower:
            question = advance_state(session, current_state, flow_step['next_state'])
            if question: resp.message(question)
        else:
            resp.message(f'Por favor, envía una foto (máximo {MAX_PHOTOS}) o escribe "listo".')
        if session['state'] == 'report_complete':
            try:
                pdf1_path = create_reporte1_pdf(session['report_data'])
                pdf1_url = url_for('static', filename=pdf1_path, _external=True)
                resp.message().media(pdf1_url)
                pdf2_path = create_reporte2_pdf(session['report_data'], account_sid, auth_token)
                pdf2_url = url_for('static', filename=pdf2_path, _external=True)
                resp.message().media(pdf2_url)
                if os.path.exists('temp_images'):
                    for f in os.listdir('temp_images'): os.remove(os.path.join('temp_images', f))
            except Exception as e:
                print(f"!!! ERROR FATAL al crear o enviar PDFs: {e}")
                resp.message("Lo siento, tuve un problema crítico al generar tus reportes en PDF.")
    else:
        if current_state == 'report_complete':
             resp.message("Reportes ya completados. Escribe 'iniciar' para comenzar de nuevo.")
             return str(resp)
        session['report_data'][flow_step['key']] = incoming_msg_original
        question = advance_state(session, current_state, flow_step['next_state'])
        if question: resp.message(question)

    return str(resp)

# --- 4. INICIAR LA APLICACIÓN ---
if __name__ == "__main__":
    app.run(debug=True, port=5001)