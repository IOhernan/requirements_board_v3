import os
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, Response
from flask_session import Session
import sqlite3
from datetime import datetime
import logging
import csv
import io

app = Flask(__name__)
app.logger.setLevel(logging.INFO)
load_dotenv()

# Configuraciones
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default_secret_key')
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

# Función para conectar a la base de datos
def get_db():
    conn = sqlite3.connect('requirements.db')
    conn.row_factory = sqlite3.Row
    return conn

# Inicializar y migrar la base de datos
def init_db():
    with get_db() as conn:
        c = conn.cursor()
        # Verificar si la tabla existe
        c.execute('PRAGMA table_info(requirements)')
        columns = [row['name'] for row in c.fetchall()]
        
        # Crear tabla si no existe o migrar
        if not columns:
            c.execute('''CREATE TABLE requirements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL,
                priority TEXT,
                progress INTEGER DEFAULT 0,
                unit TEXT,
                developer TEXT,
                created_at TEXT,
                user_id INTEGER DEFAULT 1
            )''')
        else:
            # Migrar columnas si faltan
            if 'priority' not in columns:
                c.execute('ALTER TABLE requirements ADD COLUMN priority TEXT')
            if 'progress' not in columns:
                c.execute('ALTER TABLE requirements ADD COLUMN progress INTEGER DEFAULT 0')
            if 'unit' not in columns:
                c.execute('ALTER TABLE requirements ADD COLUMN unit TEXT')
            if 'developer' not in columns:
                c.execute('ALTER TABLE requirements ADD COLUMN developer TEXT DEFAULT "No asignado"')

        # Crear otras tablas si no existen
        c.execute('''CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requirement_id INTEGER,
            comment TEXT NOT NULL,
            created_at TEXT,
            FOREIGN KEY (requirement_id) REFERENCES requirements(id)
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requirement_id INTEGER,
            action TEXT NOT NULL,
            timestamp TEXT,
            FOREIGN KEY (requirement_id) REFERENCES requirements(id)
        )''')
        conn.commit()

# Ruta principal: Tablero
@app.route('/')
def index():
    print("Cargando index.html con versión: 7f8e9d2a-3c5b-4e1d-9a6f-8b2d3e1c5a4d")
    requirements_with_comments = []
    search = request.args.get('search', '').strip()
    status_filter = request.args.get('status', '')
    priority_filter = request.args.get('priority', '')
    unit_filter = request.args.get('unit', '')
    developer_filter = request.args.get('developer', '')

    query = 'SELECT * FROM requirements WHERE 1=1'
    params = []
    if search:
        query += ' AND (title LIKE ? OR description LIKE ? OR developer LIKE ?)'
        params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])
    if status_filter:
        query += ' AND (status = ? OR status IS NULL)'
        params.append(status_filter)
    if priority_filter:
        query += ' AND (priority = ? OR priority IS NULL)'
        params.append(priority_filter)
    if unit_filter:
        query += ' AND (unit = ? OR unit IS NULL)'
        params.append(unit_filter)
    if developer_filter:
        query += ' AND (developer = ? OR developer IS NULL)'
        params.append(developer_filter)

    app.logger.info(f"Query: {query} with params: {params}")
    with get_db() as conn:
        c = conn.cursor()
        c.execute(query, params)
        requirements = c.fetchall()
        app.logger.info(f"Found {len(requirements)} requirements")
        # Asociar comentarios a cada requerimiento
        for req in requirements:
            c.execute('SELECT * FROM comments WHERE requirement_id = ?', (req['id'],))
            comments = c.fetchall()
            req_dict = dict(req)  # Convertir sqlite3.Row a diccionario mutable
            req_dict['comments'] = comments
            requirements_with_comments.append(req_dict)
        # Contar por estado para el panel de control
        c.execute('SELECT status, COUNT(*) as count FROM requirements GROUP BY status')
        status_counts = dict(c.fetchall())
    return render_template('index.html', requirements=requirements_with_comments, search=search, status_filter=status_filter, priority_filter=priority_filter, unit_filter=unit_filter, developer_filter=developer_filter, status_counts=status_counts)

# Ruta para agregar un requerimiento
@app.route('/add', methods=['POST'])
def add_requirement():
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    status = request.form.get('status', 'Pendiente')
    priority = request.form.get('priority', 'Media')
    progress = request.form.get('progress', 0)
    unit = request.form.get('unit', 'Imagine').strip()
    developer = request.form.get('developer', 'No asignado').strip()

    if not title:
        flash('El campo título es requerido.', 'error')
        return redirect(url_for('index', _anchor='added'))
    if not isinstance(title, str):
        flash('El título debe ser texto.', 'error')
        return redirect(url_for('index', _anchor='added'))
    try:
        progress = int(progress)
        if progress < 0 or progress > 100:
            flash('El progreso debe estar entre 0 y 100.', 'error')
            return redirect(url_for('index', _anchor='added'))
    except ValueError:
        flash('El progreso debe ser un número.', 'error')
        return redirect(url_for('index', _anchor='added'))

    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    user_id = 1  # Temporal

    with get_db() as conn:
        c = conn.cursor()
        c.execute('INSERT INTO requirements (title, description, status, priority, progress, unit, developer, created_at, user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                  (title, description, status, priority, progress, unit, developer, created_at, user_id))
        req_id = c.lastrowid
        c.execute('INSERT INTO history (requirement_id, action, timestamp) VALUES (?, ?, ?)',
                  (req_id, 'created', created_at))
        conn.commit()

    flash('Requerimiento creado exitoso.', 'success')
    return redirect(url_for('index', _anchor='added'))

# Ruta para agregar un comentario
@app.route('/add_comment/<int:requirement_id>', methods=['POST'])
def add_comment(requirement_id):
    comment = request.form.get('comment', '').strip()
    if not comment:
        flash('El campo comentario es requerido.', 'error')
        return redirect(url_for('index', _anchor='added'))

    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    with get_db() as conn:
        c = conn.cursor()
        c.execute('INSERT INTO comments (requirement_id, comment, created_at) VALUES (?, ?, ?)',
                  (requirement_id, comment, created_at))
        c.execute('INSERT INTO history (requirement_id, action, timestamp) VALUES (?, ?, ?)',
                  (requirement_id, 'comment_added', created_at))
        conn.commit()

    flash('Comentario agregado exitoso.', 'success')
    return redirect(url_for('index', _anchor='added'))

# Ruta para actualizar el estado vía AJAX
@app.route('/update_status/<int:id>', methods=['POST'])
def update_status(id):
    new_status = request.form.get('status')
    app.logger.info(f'Updating status for ID {id}: received status="{new_status}"')
    if not new_status or new_status not in ['Pendiente', 'En Progreso', 'Completado']:
        app.logger.warning(f'Invalid status for ID {id}: "{new_status}"')
        return jsonify({'success': False, 'error': 'Estado inválido'}), 400

    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM requirements WHERE id = ?', (id,))
        req = c.fetchone()
        if not req:
            app.logger.warning(f'Requirement ID {id} not found')
            return jsonify({'success': False, 'error': 'Requerimiento no encontrado'}), 404

        c.execute('UPDATE requirements SET status = ? WHERE id = ?', (new_status, id))
        c.execute('INSERT INTO history (requirement_id, action, timestamp) VALUES (?, ?, ?)',
                  (id, f'status_changed_to_{new_status}', datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        app.logger.info(f'Status updated for ID {id} to "{new_status}"')

    return jsonify({'success': True, 'new_status': new_status})

# Ruta para editar un requerimiento
@app.route('/edit/<int:id>', methods=['POST'])
def edit_requirement(id):
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    status = request.form.get('status', '')
    priority = request.form.get('priority', '')
    progress = request.form.get('progress', '')
    unit = request.form.get('unit', '').strip()
    developer = request.form.get('developer', '')

    if not title:
        flash('El campo título es requerido.', 'error')
        return redirect(url_for('index', _anchor=f'edit-form-{id}'))
    if not isinstance(title, str):
        flash('El título debe ser texto.', 'error')
        return redirect(url_for('index', _anchor=f'edit-form-{id}'))
    try:
        progress = int(progress) if progress else 0
        if progress < 0 or progress > 100:
            flash('El progreso debe estar entre 0 y 100.', 'error')
            return redirect(url_for('index', _anchor=f'edit-form-{id}'))
    except ValueError:
        flash('El progreso debe ser un número.', 'error')
        return redirect(url_for('index', _anchor=f'edit-form-{id}'))

    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM requirements WHERE id = ?', (id,))
        req = c.fetchone()
        if not req:
            flash('Requerimiento no encontrado.', 'error')
            return redirect(url_for('index', _anchor=f'edit-form-{id}'))

        c.execute('UPDATE requirements SET title = ?, description = ?, status = ?, priority = ?, progress = ?, unit = ?, developer = ? WHERE id = ?',
                  (title, description, status or req['status'], priority or req['priority'], progress, unit or req['unit'], developer or req['developer'], id))
        c.execute('INSERT INTO history (requirement_id, action, timestamp) VALUES (?, ?, ?)',
                  (id, 'edited', datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()

    flash('Requerimiento actualizado exitoso.', 'success')
    return redirect(url_for('index', _anchor=f'edit-form-{id}'))

# Ruta para exportar a CSV
@app.route('/export_csv')
def export_csv():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT r.id, r.title, r.description, r.status, r.priority, r.progress, r.unit, r.developer, r.created_at, c.comment, c.created_at as comment_date, h.action, h.timestamp as history_date FROM requirements r LEFT JOIN comments c ON r.id = c.requirement_id LEFT JOIN history h ON r.id = h.requirement_id')
        rows = c.fetchall()

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(['ID', 'Título', 'Descripción', 'Estado', 'Prioridad', 'Progreso', 'Unidad', 'Desarrollador', 'Fecha de Creación', 'Comentario', 'Fecha Comentario', 'Acción', 'Fecha Acción'])
    current_req = None
    for row in rows:
        req_id = row['id']
        if current_req != req_id:
            writer.writerow([row['id'], row['title'], row['description'] or '', row['status'], row['priority'] or '', row['progress'], row['unit'] or '', row['developer'] or '', row['created_at'], '', '', '', ''])
            current_req = req_id
        if row['comment']:
            writer.writerow(['', '', '', '', '', '', '', '', '', row['comment'], row['comment_date'], '', ''])
        if row['action']:
            writer.writerow(['', '', '', '', '', '', '', '', '', '', '', row['action'], row['history_date']])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=requerimientos.csv"}
    )

if __name__ == '__main__':
    init_db()
    app.run(debug=True)