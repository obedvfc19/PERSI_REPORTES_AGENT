import os
import requests
import uuid
import io
import sys
from flask import Flask, request, url_for
from twilio.twiml.messaging_response import MessagingResponse
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from PIL import Image
from dotenv import load_dotenv

# --- 0. INICIALIZACIÓN Y CARGA DE CREDENCIALES ---
load_dotenv()
app = Flask(__name__, static_folder='static')
user_sessions = {}

# --- 1. GUION DE LA CONVERSACIÓN ---
REPORT_FLOW = {
    'awaiting_start':         { 'key': 'Inicio', 'next_state': 'awaiting_ot'},
    'awaiting_ot':              { 'key': 'OT', 'next_state': 'awaiting_fecha', 'question': '✅ Reporte iniciado. Por favor, ingresa la *OT (Orden de Trabajo)*.'},
    'awaiting_fecha':           { 'key': 'Fecha', 'next_state': 'awaiting_area', 'question': 'Ahora, por favor, escribe la *Fecha*.'},
    'awaiting_area':            { 'key': 'Área', 'next_state': 'awaiting_lugar', 'question': 'Ingresa el *Área* de trabajo.'},
    'awaiting_lugar':           { 'key': 'Lugar', 'next_state': 'awaiting_supervisor_calidra', 'question': 'Gracias. Ahora, escribe el *Lugar* específico.'},
    'awaiting_supervisor_calidra': { 'key': 'Supervisor Calidra', 'next_state': 'awaiting_supervisor_persi', 'question': 'Entendido. ¿Quién es el *Supervisor Calidra*?'},
    'awaiting_supervisor_persi':{ 'key': 'Supervisor Persi', 'next_state': 'awaiting_intervienen', 'question': '¿Y el *Supervisor Persi*?'},
    'awaiting_intervienen':     { 'key': 'Quienes interviene', 'next_state': 'awaiting_descripcion', 'question': 'Anotado. ¿*Quiénes más intervienen* en el trabajo?'},
    'awaiting_descripcion':     { 'key': 'Descripcion de Actividad', 'next_state': 'awaiting_duracion', 'question': 'Perfecto. Agrega la *Descripción de Actividad*.'},
    'awaiting_duracion':        { 'key': 'Duracion del trabajo', 'next_state': 'awaiting_fotos_antes', 'question': 'Casi terminamos. ¿Cuál es la *Duración del trabajo*?'},
    'awaiting_fotos_antes':     { 'key': 'Fotos_antes', 'next_state': 'awaiting_fotos_despues', 'question': 'Ahora, envía las *fotos de ANTES*. Puedes enviar varias. Cuando termines, escribe "listo".'},
    'awaiting_fotos_despues':   { 'key': 'Fotos_despues', 'next_state': 'report_complete', 'question': 'Fotos de "antes" recibidas. ✅ Ahora, envía las *fotos de DESPUÉS*. Puedes enviar varias. Cuando termines, escribe "listo".'},
    'report_complete':          { 'key': 'Completo', 'next_state': 'report_complete', 'question': 'Fotos de "después" recibidas. ✅ ¡Reporte completado! Estoy generando tu PDF, por favor espera un momento...'}
}

# --- 2. FUNCIÓN PARA CREAR EL PDF (VERSIÓN FINAL MODIFICADA) ---
def create_pdf(report_data, account_sid, auth_token):
    template_path = "REPORTE1.pdf"
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=letter)
    can.setFont("Helvetica", 9)

    # Coordenadas de texto
    can.drawString(175, 750, str(report_data.get('Área', '')))
    can.drawString(175, 738, str(report_data.get('Lugar', '')))
    can.drawString(432, 750, str(report_data.get('Fecha', '')))
    can.drawString(432, 738, str(report_data.get('OT', '')))
    can.drawString(175, 726, str(report_data.get('Supervisor Calidra', '')))
    can.drawString(390, 726, str(report_data.get('Supervisor Persi', '')))
    
    # Lógica de ajuste de texto para "Descripción"
    text_object = can.beginText()
    text_object.setTextOrigin(35, 700)
    text_object.setFont("Helvetica", 9)
    max_width_desc = 470
    description_text = str(report_data.get('Descripcion de Actividad', ''))
    words = description_text.split()
    line = ''
    for word in words:
        if can.stringWidth(line + ' ' + word, "Helvetica", 9) < max_width_desc:
            line += ' ' + word
        else:
            text_object.textLine(line.strip())
            line = word
    text_object.textLine(line.strip())
    can.drawText(text_object)
    
    can.drawString(75, 592, str(report_data.get('Supervisor Persi', '')))
    can.drawString(320, 592, str(report_data.get('Duracion del trabajo', '')))

    # Lógica de imágenes
    def add_image_gallery(urls, x_start, y_top, max_width):
        y_cursor = y_top
        for url in urls:
            display_h = 0
            try:
                response = requests.get(url, auth=(account_sid, auth_token), timeout=20)
                if response.status_code == 200:
                    temp_path = os.path.join('temp_images', str(uuid.uuid4()))
                    with open(temp_path, 'wb') as f: f.write(response.content)
                    with Image.open(temp_path) as img:
                        # --- MODIFICACIÓN AQUÍ ---
                        # Se eliminó el cálculo del aspect ratio para forzar el tamaño.
                        # El ancho es `max_width` (225) y el alto es fijo `250`.
                        display_w, display_h = max_width, 235 
                        
                        y_coord_from_bottom = y_cursor - display_h
                        can.drawImage(temp_path, x_start, y_coord_from_bottom, width=display_w, height=display_h, mask='auto')
                else: raise Exception(f"Estado de descarga: {response.status_code}")
                display_h += 5
            except Exception as e:
                print(f"!!! ERROR al procesar imagen {url}: {e}")
                error_box_h = 40
                y_coord_from_bottom = y_cursor - error_box_h
                can.setFillColorRGB(1, 0.9, 0.9); can.rect(x_start, y_coord_from_bottom, max_width, error_box_h, fill=1, stroke=0)
                can.setFillColorRGB(0.7, 0, 0); can.drawString(x_start + 5, y_cursor - 25, "Error al cargar la imagen."); can.setFillColorRGB(0, 0, 0)
                display_h = error_box_h + 5
            y_cursor -= display_h

    if not os.path.exists('temp_images'): os.makedirs('temp_images')
    add_image_gallery(report_data.get('Fotos_antes', []), x_start=40, y_top=570, max_width=225)
    add_image_gallery(report_data.get('Fotos_despues', []), x_start=277, y_top=570, max_width=225)

    # Fusión y guardado del PDF
    can.save()
    packet.seek(0)
    new_pdf = PdfReader(packet)
    existing_pdf = PdfReader(open(template_path, "rb"))
    output = PdfWriter()
    page = existing_pdf.pages[0]
    page.merge_page(new_pdf.pages[0])
    output.add_page(page)
    if not os.path.exists('static/reports'): os.makedirs('static/reports')
    pdf_filename = f'reporte_final_{uuid.uuid4()}.pdf'
    pdf_path = os.path.join(app.static_folder, 'reports', pdf_filename)
    with open(pdf_path, "wb") as outputStream: output.write(outputStream)
    if os.path.exists('temp_images'):
        for f in os.listdir('temp_images'): os.remove(os.path.join('temp_images', f))
    return os.path.join('reports', pdf_filename).replace('\\', '/')

# --- 3. LÓGICA PRINCIPAL DEL BOT ---
@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    sender_id = request.values.get('From', '')
    incoming_msg_original = request.values.get('Body', '').strip()
    incoming_msg_lower = incoming_msg_original.lower()
    media_urls = [request.values.get(f'MediaUrl{i}') for i in range(int(request.values.get('NumMedia', 0)))]
    resp = MessagingResponse()
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")

    if sender_id not in user_sessions or 'iniciar' in incoming_msg_lower:
        user_sessions[sender_id] = {'state': 'awaiting_start', 'report_data': {}}
    
    session = user_sessions[sender_id]
    current_state = session['state']
    flow_step = REPORT_FLOW[current_state]

    if current_state == 'report_complete':
        resp.message("Reporte ya completado. Escribe 'iniciar' para comenzar otro.")
    elif current_state == 'awaiting_start':
        session['state'] = flow_step['next_state']
        resp.message(REPORT_FLOW[session['state']]['question'])
    elif 'fotos' in current_state:
        if media_urls:
            if flow_step['key'] not in session['report_data']: session['report_data'][flow_step['key']] = []
            session['report_data'][flow_step['key']].extend(media_urls)
            resp.message('Foto(s) recibida(s). Envía más o escribe "listo".')
        elif 'listo' in incoming_msg_lower:
            session['state'] = flow_step['next_state']
            next_question = REPORT_FLOW[session['state']]['question']
            
            if session['state'] == 'report_complete':
                resp.message(next_question)
                try:
                    pdf_relative_path = create_pdf(session['report_data'], account_sid, auth_token)
                    pdf_url = url_for('static', filename=pdf_relative_path, _external=True)
                    message = resp.message()
                    message.media(pdf_url)
                except Exception as e:
                    print(f"!!! ERROR FATAL al crear o enviar PDF: {e}")
                    resp.message("Lo siento, tuve un problema crítico al generar tu PDF.")
            else:
                resp.message(next_question)
        else:
            resp.message('Por favor, envía una foto o escribe "listo".')
    else: 
        session['report_data'][flow_step['key']] = incoming_msg_original
        session['state'] = flow_step['next_state']
        resp.message(REPORT_FLOW[session['state']]['question'])
            
    return str(resp)

# --- 4. INICIAR LA APLICACIÓN ---
if __name__ == "__main__":
    app.run(debug=True, port=5001)

