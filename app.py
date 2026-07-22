import os
import requests
import uuid
from flask import Flask, request, url_for
from twilio.twiml.messaging_response import MessagingResponse
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak, KeepTogether
)
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

## Generación de PDF (reconstrucción dinámica con ReportLab)
# Se genera un ÚNICO PDF que contiene la Cotización y el Reporte de Actividades.
# Las tablas y bloques de texto crecen automáticamente según su contenido y el
# documento agrega las páginas que sean necesarias sin cortar información.

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(BASE_DIR, 'logo_persi.png')

# Colores muestreados de las plantillas originales
PDF_GREEN = colors.Color(167 / 255, 235 / 255, 133 / 255)
PDF_NAVY = colors.Color(41 / 255, 55 / 255, 97 / 255)

PAGE_W, PAGE_H = A4
PAGE_MARGIN = 25
USABLE_W = PAGE_W - 2 * PAGE_MARGIN

_base_styles = getSampleStyleSheet()
_S_CELL = ParagraphStyle('cell', parent=_base_styles['Normal'], fontName='Helvetica',
                         fontSize=8, leading=10)
_S_CELL_C = ParagraphStyle('cellc', parent=_S_CELL, alignment=TA_CENTER)
_S_LABEL = ParagraphStyle('label', parent=_base_styles['Normal'], fontName='Helvetica-Bold',
                          fontSize=9, leading=11)
_S_VAL = ParagraphStyle('val', parent=_base_styles['Normal'], fontName='Helvetica',
                        fontSize=9, leading=11)
_S_BAND = ParagraphStyle('band', parent=_base_styles['Normal'], fontName='Helvetica-Bold',
                         fontSize=11, leading=13, alignment=TA_CENTER)
_S_TITLE = ParagraphStyle('title', parent=_base_styles['Normal'], fontName='Helvetica-Bold',
                          fontSize=16, leading=19, alignment=TA_CENTER)
_S_COMPANY = ParagraphStyle('company', parent=_base_styles['Normal'], fontName='Helvetica-Bold',
                            fontSize=7, leading=8.5)
_S_SIGN = ParagraphStyle('sign', parent=_base_styles['Normal'], fontName='Helvetica-Bold',
                         fontSize=11, leading=14, alignment=TA_CENTER)
_S_SIGN_SUB = ParagraphStyle('signsub', parent=_base_styles['Normal'], fontName='Helvetica-Bold',
                             fontSize=9, leading=12, alignment=TA_CENTER)


def _pdf_band(text, width=USABLE_W):
    t = Table([[Paragraph(text, _S_BAND)]], colWidths=[width])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), PDF_GREEN),
        ('BOX', (0, 0), (-1, -1), 0.8, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    return t


def _pdf_header(title_text):
    company = ("CONSTRUCCIONES Y SERVICIOS PERSI S.A. de C.V.<br/>"
               "Registro Federal de Contribuyentes CSP160505- J66<br/>"
               "Calle Arquimedes V. # 1403 col. Tecnologico<br/>"
               "Monclova Coahuila Mexico Cp. 25716<br/>"
               "E-mail: persi.ceo@hotmail.com / persi.pro@hotmail.com<br/>"
               "Tel: Oficina 229-532-47-23 / celular 866-135-80-72")
    try:
        logo = Image(LOGO_PATH, width=95, height=75)
    except Exception:
        logo = Spacer(95, 75)
    right = Table([[Paragraph(title_text, _S_TITLE)],
                   [Paragraph(company, _S_COMPANY)]], colWidths=[USABLE_W - 120])
    right.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), PDF_GREEN),
        ('BOX', (0, 0), (0, 0), 0.8, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 1), (0, 1), 2),
        ('LEFTPADDING', (0, 1), (0, 1), 4),
    ]))
    outer = Table([[logo, right]], colWidths=[120, USABLE_W - 120])
    outer.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (0, 0), 'CENTER'),
    ]))
    return outer


def _pdf_info_block(d):
    def L(t):
        return Paragraph(t, _S_LABEL)

    def V(t):
        return Paragraph(str(t if t is not None else ''), _S_VAL)

    c = [70, USABLE_W * 0.30, 78, 70, 95,
         USABLE_W - (70 + USABLE_W * 0.30 + 78 + 70 + 95)]
    rows = [
        [L('FOLIO:'), V(''), '', '', '', ''],
        [L('Area de trabajo:'), V(d.get('Area de trabajo')), L('Fecha:'), V(d.get('Fecha')), '', ''],
        [L('Lugar:'), V(d.get('Lugar')), L('O.T.'), V(d.get('O.T.')),
         L('Duracion de trabajo:'), V(d.get('Duracion de trabajo'))],
        [L('Trabajadores:'), V(d.get('Trabajadores')), L('Usuario Calidra:'),
         V(d.get('Usuario Calidra')), '', ''],
        ['', '', L('Supervisor PERSI:'), V(d.get('Supervisor PERSI')), '', ''],
    ]
    t = Table(rows, colWidths=c)
    t.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.6, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('SPAN', (1, 0), (5, 0)),
        ('SPAN', (3, 1), (5, 1)),
        ('SPAN', (3, 3), (5, 3)),
        ('SPAN', (3, 4), (5, 4)),
        ('SPAN', (0, 3), (0, 4)),
        ('SPAN', (1, 3), (1, 4)),
    ]))
    return t


def _pdf_partidas_table(d):
    hs = ParagraphStyle('hdr', parent=_S_CELL_C, fontName='Helvetica-Bold', fontSize=7.5)
    header = [Paragraph('PARTIDA', hs), Paragraph('DESCRIPCION', hs),
              Paragraph('UNI.MEDIDA', hs), Paragraph('CANTIDAD', hs),
              Paragraph('p/u', hs), Paragraph('TOTAL', hs)]
    rows = [header]
    for i, p in enumerate(d.get('Partidas', []), 1):
        try:
            pu = float(p.get('pu', 0))
            tot = float(p.get('total', 0))
        except (ValueError, TypeError):
            pu = tot = 0
        rows.append([
            Paragraph(str(i), _S_CELL_C),
            Paragraph(str(p.get('descripcion', '')), _S_CELL),
            Paragraph(str(p.get('um', '')), _S_CELL_C),
            Paragraph(str(p.get('cantidad', '')), _S_CELL_C),
            Paragraph(f"${pu:,.2f}", _S_CELL_C),
            Paragraph(f"${tot:,.2f}", _S_CELL_C),
        ])
    gt = d.get('grand_total', 0)
    gt_style = ParagraphStyle('gt', parent=_S_CELL_C, fontName='Helvetica-Bold', fontSize=8.5)
    rows.append([Paragraph('TOTAL:', _S_LABEL), '', '', '', '',
                 Paragraph(f"${gt:,.2f}", gt_style)])
    widths = [46, USABLE_W - (46 + 58 + 50 + 58 + 72), 58, 50, 58, 72]
    t = Table(rows, colWidths=widths, repeatRows=1)
    n = len(rows)
    t.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -2), 0.6, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), PDF_GREEN),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('VALIGN', (1, 1), (1, -2), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, 0), 2),
        ('RIGHTPADDING', (0, 0), (-1, 0), 2),
        ('LEFTPADDING', (2, 1), (-1, -1), 2),
        ('RIGHTPADDING', (2, 1), (-1, -1), 2),
        ('SPAN', (0, n - 1), (4, n - 1)),
        ('LINEABOVE', (0, n - 1), (-1, n - 1), 0.8, colors.black),
        ('BOX', (5, n - 1), (5, n - 1), 0.6, colors.black),
        ('ALIGN', (0, n - 1), (0, n - 1), 'RIGHT'),
    ]))
    return t


def _pdf_sign_boxes():
    def box(role):
        supervisor = 'PERSI' if role == 'Elaboro' else 'CALIDRA'
        inner = Table([[Paragraph(role, _S_SIGN)],
                       [Spacer(1, 28)],
                       [Paragraph('_______________________________', _S_SIGN_SUB)],
                       [Paragraph('Nombre y Firma (Supervisor %s)' % supervisor, _S_SIGN_SUB)]],
                      colWidths=[USABLE_W / 2 - 20])
        inner.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1.2, PDF_NAVY),
            ('ROUNDEDCORNERS', [8, 8, 8, 8]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
        ]))
        return inner
    outer = Table([[box('Elaboro'), box('Recibio')]],
                  colWidths=[USABLE_W / 2, USABLE_W / 2])
    outer.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                               ('LEFTPADDING', (0, 0), (-1, -1), 6),
                               ('RIGHTPADDING', (0, 0), (-1, -1), 6)]))
    return outer


def _pdf_fotos(d):
    def gallery(paths):
        cells = []
        for p in (paths or []):
            if p and os.path.exists(p):
                try:
                    cells.append([Image(p, width=USABLE_W / 2 - 14, height=150)])
                except Exception as e:
                    print(f"!!! ERROR al dibujar la imagen {p}: {e}")
                    cells.append([Spacer(1, 150)])
        if not cells:
            cells = [[Spacer(1, 150)]]
        inner = Table(cells, colWidths=[USABLE_W / 2 - 10])
        inner.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                   ('TOPPADDING', (0, 0), (-1, -1), 4),
                                   ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                                   ('ALIGN', (0, 0), (-1, -1), 'CENTER')]))
        return inner
    band = Table([[Paragraph('FOTOS ANTES DE LA ACTIVIDAD', _S_BAND),
                   Paragraph('FOTOS DESPUES DE LA ACTIVIDAD', _S_BAND)]],
                 colWidths=[USABLE_W / 2, USABLE_W / 2])
    band.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), PDF_GREEN),
                              ('GRID', (0, 0), (-1, -1), 0.8, colors.black),
                              ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                              ('TOPPADDING', (0, 0), (-1, -1), 4),
                              ('BOTTOMPADDING', (0, 0), (-1, -1), 4)]))
    gal = Table([[gallery(d.get('Fotos_antes', [])), gallery(d.get('Fotos_despues', []))]],
                colWidths=[USABLE_W / 2, USABLE_W / 2])
    gal.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 0.8, colors.black),
                             ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    return band, gal


def create_unified_pdf(report_data):
    """Genera un único PDF (Cotización + Reporte de Actividades) con altura de
    bloques dinámica y paginación automática. Devuelve la ruta relativa dentro
    de la carpeta static."""
    if not os.path.exists('static/reports'):
        os.makedirs('static/reports')
    pdf_filename = f'reporte_persi_{uuid.uuid4()}.pdf'
    pdf_path = os.path.join(app.static_folder, 'reports', pdf_filename)

    doc = BaseDocTemplate(pdf_path, pagesize=A4,
                          leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN,
                          topMargin=PAGE_MARGIN, bottomMargin=PAGE_MARGIN)
    frame = Frame(PAGE_MARGIN, PAGE_MARGIN, USABLE_W, PAGE_H - 2 * PAGE_MARGIN,
                  id='main', leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id='main', frames=[frame])])

    story = []

    # ---------- COTIZACIÓN ----------
    story.append(_pdf_header('COTIZACION'))
    story.append(Spacer(1, 4))
    story.append(_pdf_info_block(report_data))
    story.append(Spacer(1, 4))
    story.append(_pdf_partidas_table(report_data))
    story.append(Spacer(1, 4))
    cbox = Table([[Paragraph(str(report_data.get('Comentarios de seguridad', '') or ''), _S_VAL)]],
                 colWidths=[USABLE_W])
    cbox.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), 0.6, colors.black),
                              ('TOPPADDING', (0, 0), (-1, -1), 6),
                              ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                              ('LEFTPADDING', (0, 0), (-1, -1), 6)]))
    story.append(KeepTogether([_pdf_band('COMENTARIOS DE SEGURIDAD'), cbox]))
    story.append(Spacer(1, 10))
    story.append(KeepTogether(_pdf_sign_boxes()))
    story.append(PageBreak())

    # ---------- REPORTE DE ACTIVIDADES ----------
    story.append(_pdf_header('REPORTE DE ACTIVIDADES'))
    story.append(Spacer(1, 4))
    story.append(_pdf_info_block(report_data))
    story.append(Spacer(1, 4))
    dbox = Table([[Paragraph(str(report_data.get('Descripcion general', '') or ''), _S_VAL)]],
                 colWidths=[USABLE_W])
    dbox.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), 0.6, colors.black),
                              ('TOPPADDING', (0, 0), (-1, -1), 8),
                              ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                              ('LEFTPADDING', (0, 0), (-1, -1), 6)]))
    story.append(KeepTogether([_pdf_band('DESCRIPCION DE ACTIVIDAD'), dbox]))
    story.append(Spacer(1, 4))
    band, gal = _pdf_fotos(report_data)
    story.append(KeepTogether([band, gal]))
    story.append(Spacer(1, 10))
    story.append(KeepTogether([_pdf_band('FIRMAS DE LA ACTIVIDAD'), Spacer(1, 6),
                               _pdf_sign_boxes()]))
    story.append(Spacer(1, 4))
    story.append(Paragraph('FR-CAL-014',
                           ParagraphStyle('foot', parent=_S_LABEL, alignment=2)))

    doc.build(story)
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
                pdf_path = create_unified_pdf(session['report_data'])
                pdf_url = url_for('static', filename=pdf_path, _external=True)
                resp.message().media(pdf_url)
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