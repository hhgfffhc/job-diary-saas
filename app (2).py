"""
🏗️ Job Diary Pro v7 SaaS - Multi-Tenant Business Management Suite
Production-ready with Celery, PostgreSQL, Stripe, and Multi-tenant support
"""

import os
import json
import csv
import io
import re
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, request, render_template_string, redirect, session, url_for, Response, jsonify, send_file, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.dialects.postgresql import UUID
import uuid

from celery import Celery
from celery.schedules import crontab

import stripe
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import inch, mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_LEFT, TA_CENTER
from io import BytesIO
from PIL import Image as PILImage

# =========================
# APP INITIALIZATION
# =========================
app = Flask(__name__)
app.config.from_object('config.Config')

# Database
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Celery
def make_celery(app):
    celery = Celery(
        app.import_name,
        backend=app.config['CELERY_RESULT_BACKEND'],
        broker=app.config['CELERY_BROKER_URL']
    )
    celery.conf.update(app.config)
    
    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)
    
    celery.Task = ContextTask
    return celery

celery = make_celery(app)
stripe.api_key = app.config['STRIPE_SECRET_KEY']

# =========================
# DATABASE MODELS
# =========================
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255))
    first_name = db.Column(db.String(120))
    last_name = db.Column(db.String(120))
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey('tenant.id'), nullable=False, index=True)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    tenant = db.relationship('Tenant', backref='users')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Tenant(db.Model):
    __tablename__ = 'tenant'
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    subscription_plan = db.Column(db.String(50), default='free')  # free, pro, enterprise
    stripe_customer_id = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Company Settings
    company_email = db.Column(db.String(120))
    company_phone = db.Column(db.String(20))
    company_address = db.Column(db.Text)
    vat_number = db.Column(db.String(50))
    tax_rate = db.Column(db.Float, default=0.20)
    currency = db.Column(db.String(3), default='GBP')
    logo_path = db.Column(db.String(255))
    accent_color = db.Column(db.String(7), default='#0d9488')
    invoice_footer = db.Column(db.Text)
    
    # Relationships
    clients = db.relationship('Client', backref='tenant', lazy='dynamic', cascade='all, delete-orphan')
    jobs = db.relationship('Job', backref='tenant', lazy='dynamic', cascade='all, delete-orphan')
    invoices = db.relationship('Invoice', backref='tenant', lazy='dynamic', cascade='all, delete-orphan')

class Client(db.Model):
    __tablename__ = 'clients'
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey('tenant.id'), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    company_name = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('tenant_id', 'email', name='_tenant_client_email_uc'),)

class Job(db.Model):
    __tablename__ = 'jobs'
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey('tenant.id'), nullable=False, index=True)
    customer = db.Column(db.String(255), nullable=False)
    phone_number = db.Column(db.String(20))
    description = db.Column(db.Text)
    address = db.Column(db.Text)
    date = db.Column(db.Date, nullable=False, index=True)
    time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time)
    email = db.Column(db.String(120))
    notified_24h = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Invoice(db.Model):
    __tablename__ = 'invoices'
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = db.Column(UUID(as_uuid=True), db.ForeignKey('tenant.id'), nullable=False, index=True)
    invoice_number = db.Column(db.String(50), nullable=False, index=True)
    client_id = db.Column(UUID(as_uuid=True), db.ForeignKey('clients.id'), nullable=False)
    invoice_date = db.Column(db.Date, default=datetime.utcnow)
    due_date = db.Column(db.Date)
    subtotal = db.Column(db.Float)
    tax_amount = db.Column(db.Float)
    total = db.Column(db.Float)
    status = db.Column(db.String(50), default='draft')  # draft, sent, paid, unpaid, overdue
    notes = db.Column(db.Text)
    payment_terms = db.Column(db.String(50))
    stripe_payment_id = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    client = db.relationship('Client', backref='invoices')
    items = db.relationship('InvoiceItem', backref='invoice', lazy='dynamic', cascade='all, delete-orphan')
    payments = db.relationship('Payment', backref='invoice', lazy='dynamic', cascade='all, delete-orphan')
    
    __table_args__ = (db.UniqueConstraint('tenant_id', 'invoice_number', name='_tenant_invoice_number_uc'),)

class InvoiceItem(db.Model):
    __tablename__ = 'invoice_items'
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id = db.Column(UUID(as_uuid=True), db.ForeignKey('invoices.id'), nullable=False)
    description = db.Column(db.String(255))
    quantity = db.Column(db.Float)
    rate = db.Column(db.Float)
    amount = db.Column(db.Float)

class Payment(db.Model):
    __tablename__ = 'payments'
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id = db.Column(UUID(as_uuid=True), db.ForeignKey('invoices.id'), nullable=False)
    payment_date = db.Column(db.Date, default=datetime.utcnow)
    amount = db.Column(db.Float)
    payment_method = db.Column(db.String(50))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# =========================
# LOGIN MANAGER
# =========================
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(user_id)

# =========================
# DECORATORS
# =========================
def tenant_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# =========================
# CELERY TASKS
# =========================
@celery.task
def send_email_task(to_email, subject, body):
    """Send email asynchronously"""
    from tasks import send_email
    return send_email(to_email, subject, body)

@celery.task
def check_24h_reminders_task():
    """Check and send 24-hour job reminders"""
    from tasks import check_24h_reminders
    return check_24h_reminders()

@celery.task
def generate_pdf_task(invoice_id):
    """Generate invoice PDF"""
    from tasks import generate_invoice_pdf
    return generate_invoice_pdf(invoice_id)

@celery.task
def check_overdue_invoices_task():
    """Mark overdue invoices"""
    tenants = Tenant.query.all()
    for tenant in tenants:
        invoices = Invoice.query.filter_by(
            tenant_id=tenant.id, 
            status='unpaid'
        ).filter(Invoice.due_date < datetime.utcnow().date()).all()
        for inv in invoices:
            inv.status = 'overdue'
        db.session.commit()

# =========================
# ROUTES - AUTHENTICATION
# =========================
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        company_name = request.form.get('company_name')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return redirect(url_for('signup'))
        
        # Create tenant
        slug = company_name.lower().replace(' ', '-')[:50]
        tenant = Tenant(company_name=company_name, slug=slug)
        db.session.add(tenant)
        db.session.flush()
        
        # Create user
        user = User(
            email=email,
            tenant_id=tenant.id,
            is_admin=True,
            first_name=request.form.get('first_name', ''),
            last_name=request.form.get('last_name', '')
        )
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        login_user(user)
        return redirect(url_for('dashboard'))
    
    return render_template_string(SIGNUP_TEMPLATE)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        
        flash('Invalid email or password', 'error')
    
    return render_template_string(LOGIN_TEMPLATE)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# =========================
# ROUTES - DASHBOARD
# =========================
@app.route('/')
@login_required
def dashboard():
    tenant = current_user.tenant
    today = datetime.utcnow().date()
    
    # Stats
    total_jobs = Job.query.filter_by(tenant_id=tenant.id).count()
    upcoming_jobs = Job.query.filter_by(tenant_id=tenant.id).filter(Job.date >= today).count()
    total_invoices = Invoice.query.filter_by(tenant_id=tenant.id).count()
    total_revenue = db.session.query(db.func.sum(Invoice.total)).filter_by(tenant_id=tenant.id).scalar() or 0
    
    # Recent jobs
    recent_jobs = Job.query.filter_by(tenant_id=tenant.id).order_by(Job.date.desc()).limit(10).all()
    
    return render_template_string(DASHBOARD_TEMPLATE, 
        tenant=tenant,
        total_jobs=total_jobs,
        upcoming_jobs=upcoming_jobs,
        total_invoices=total_invoices,
        total_revenue=total_revenue,
        recent_jobs=recent_jobs
    )

@app.route('/jobs', methods=['GET', 'POST'])
@login_required
def jobs():
    tenant = current_user.tenant
    
    if request.method == 'POST':
        job = Job(
            tenant_id=tenant.id,
            customer=request.form.get('customer'),
            phone_number=request.form.get('phone_number'),
            description=request.form.get('description'),
            address=request.form.get('address'),
            date=datetime.strptime(request.form.get('date'), '%Y-%m-%d').date(),
            time=datetime.strptime(request.form.get('time'), '%H:%M').time(),
            end_time=datetime.strptime(request.form.get('end_time'), '%H:%M').time() if request.form.get('end_time') else None,
            email=request.form.get('email')
        )
        
        db.session.add(job)
        db.session.commit()
        
        # Send confirmation email async
        send_email_task.delay(
            job.email,
            f"✅ Job Confirmation - {job.customer}",
            f"Your job has been scheduled for {job.date} at {job.time}"
        )
        
        flash('Job added successfully!', 'success')
        return redirect(url_for('jobs'))
    
    jobs_list = Job.query.filter_by(tenant_id=tenant.id).order_by(Job.date.desc()).all()
    
    return render_template_string(JOBS_TEMPLATE, jobs=jobs_list, tenant=tenant)

@app.route('/jobs/<job_id>/delete', methods=['POST'])
@login_required
def delete_job(job_id):
    job = Job.query.get(job_id)
    if job and job.tenant_id == current_user.tenant_id:
        db.session.delete(job)
        db.session.commit()
        flash('Job deleted', 'success')
    return redirect(url_for('jobs'))

@app.route('/api/jobs')
@login_required
def api_jobs():
    jobs_list = Job.query.filter_by(tenant_id=current_user.tenant_id).all()
    return jsonify([{
        'id': str(job.id),
        'customer': job.customer,
        'date': job.date.isoformat(),
        'time': str(job.time),
        'end_time': str(job.end_time) if job.end_time else None,
        'description': job.description,
        'address': job.address,
        'email': job.email
    } for job in jobs_list])

# =========================
# ROUTES - INVOICES
# =========================
@app.route('/invoices')
@login_required
def invoices():
    tenant = current_user.tenant
    check_overdue_invoices_task.delay()
    
    invoices_list = Invoice.query.filter_by(tenant_id=tenant.id).order_by(Invoice.created_at.desc()).all()
    
    # Analytics
    analytics = {
        'total': sum(inv.total or 0 for inv in invoices_list),
        'paid': sum(inv.total or 0 for inv in invoices_list if inv.status == 'paid'),
        'unpaid': sum(inv.total or 0 for inv in invoices_list if inv.status == 'unpaid'),
        'overdue': sum(inv.total or 0 for inv in invoices_list if inv.status == 'overdue')
    }
    
    return render_template_string(INVOICES_TEMPLATE, 
        invoices=invoices_list,
        analytics=analytics,
        tenant=tenant
    )

@app.route('/invoices/create', methods=['GET', 'POST'])
@login_required
def create_invoice():
    tenant = current_user.tenant
    
    if request.method == 'POST':
        client_id = request.form.get('client_id')
        
        # Generate invoice number
        last_invoice = Invoice.query.filter_by(tenant_id=tenant.id).order_by(Invoice.created_at.desc()).first()
        invoice_count = Invoice.query.filter_by(tenant_id=tenant.id).count()
        invoice_number = f"INV-{(invoice_count + 1):05d}"
        
        # Calculate totals
        descriptions = request.form.getlist('descriptions[]')
        quantities = request.form.getlist('quantities[]')
        rates = request.form.getlist('rates[]')
        
        subtotal = sum(float(q) * float(r) for q, r in zip(quantities, rates) if q and r)
        tax_amount = subtotal * tenant.tax_rate
        total = subtotal + tax_amount
        
        # Create invoice
        invoice = Invoice(
            tenant_id=tenant.id,
            invoice_number=invoice_number,
            client_id=client_id,
            subtotal=subtotal,
            tax_amount=tax_amount,
            total=total,
            due_date=datetime.utcnow().date() + timedelta(days=30),
            payment_terms=f"Net 30 days"
        )
        
        db.session.add(invoice)
        db.session.flush()
        
        # Add line items
        for desc, qty, rate in zip(descriptions, quantities, rates):
            if desc and qty and rate:
                item = InvoiceItem(
                    invoice_id=invoice.id,
                    description=desc,
                    quantity=float(qty),
                    rate=float(rate),
                    amount=float(qty) * float(rate)
                )
                db.session.add(item)
        
        db.session.commit()
        flash('Invoice created!', 'success')
        return redirect(url_for('invoice_detail', invoice_id=invoice.id))
    
    clients = Client.query.filter_by(tenant_id=tenant.id).all()
    return render_template_string(CREATE_INVOICE_TEMPLATE, clients=clients)

@app.route('/invoices/<invoice_id>')
@login_required
def invoice_detail(invoice_id):
    invoice = Invoice.query.get(invoice_id)
    
    if not invoice or invoice.tenant_id != current_user.tenant_id:
        return 'Not found', 404
    
    return render_template_string(INVOICE_DETAIL_TEMPLATE, invoice=invoice, tenant=current_user.tenant)

@app.route('/invoices/<invoice_id>/pdf')
@login_required
def invoice_pdf(invoice_id):
    invoice = Invoice.query.get(invoice_id)
    
    if not invoice or invoice.tenant_id != current_user.tenant_id:
        return 'Not found', 404
    
    pdf_buffer = generate_invoice_pdf(invoice)
    return send_file(pdf_buffer, mimetype='application/pdf', as_attachment=True, download_name=f'{invoice.invoice_number}.pdf')

@app.route('/invoices/<invoice_id>/delete', methods=['POST'])
@login_required
def delete_invoice(invoice_id):
    invoice = Invoice.query.get(invoice_id)
    
    if invoice and invoice.tenant_id == current_user.tenant_id:
        db.session.delete(invoice)
        db.session.commit()
        flash('Invoice deleted', 'success')
    
    return redirect(url_for('invoices'))

# =========================
# ROUTES - CLIENTS
# =========================
@app.route('/clients', methods=['GET', 'POST'])
@login_required
def clients():
    tenant = current_user.tenant
    
    if request.method == 'POST':
        client = Client(
            tenant_id=tenant.id,
            name=request.form.get('name'),
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            address=request.form.get('address'),
            company_name=request.form.get('company_name')
        )
        
        db.session.add(client)
        db.session.commit()
        flash('Client added!', 'success')
        return redirect(url_for('clients'))
    
    clients_list = Client.query.filter_by(tenant_id=tenant.id).all()
    return render_template_string(CLIENTS_TEMPLATE, clients=clients_list)

@app.route('/clients/<client_id>/delete', methods=['POST'])
@login_required
def delete_client(client_id):
    client = Client.query.get(client_id)
    
    if client and client.tenant_id == current_user.tenant_id:
        db.session.delete(client)
        db.session.commit()
        flash('Client deleted', 'success')
    
    return redirect(url_for('clients'))

# =========================
# ROUTES - SETTINGS
# =========================
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    tenant = current_user.tenant
    
    if request.method == 'POST':
        tenant.company_email = request.form.get('company_email')
        tenant.company_phone = request.form.get('company_phone')
        tenant.company_address = request.form.get('company_address')
        tenant.vat_number = request.form.get('vat_number')
        tenant.tax_rate = float(request.form.get('tax_rate', 0.20))
        tenant.accent_color = request.form.get('accent_color', '#0d9488')
        tenant.invoice_footer = request.form.get('invoice_footer')
        
        db.session.commit()
        flash('Settings updated!', 'success')
        return redirect(url_for('settings'))
    
    return render_template_string(SETTINGS_TEMPLATE, tenant=tenant)

@app.route('/billing')
@login_required
def billing():
    tenant = current_user.tenant
    return render_template_string(BILLING_TEMPLATE, tenant=tenant, stripe_public_key=app.config['STRIPE_PUBLIC_KEY'])

# =========================
# HELPER FUNCTIONS
# =========================
def generate_invoice_pdf(invoice):
    """Generate PDF for invoice"""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=50, leftMargin=50, topMargin=30, bottomMargin=50)
    styles = getSampleStyleSheet()
    story = []
    
    tenant = invoice.tenant
    accent = tenant.accent_color or '#0d9488'
    
    try:
        accent_rgb = colors.HexColor(accent)
    except:
        accent_rgb = colors.HexColor('#0d9488')
    
    # Header
    header_data = [[
        Paragraph(f"<b>{tenant.company_name}</b>", styles['Heading1']),
        Paragraph(f"<b>INVOICE #{invoice.invoice_number}</b>", ParagraphStyle("", fontSize=20, textColor=colors.white, fontName="Helvetica-Bold"))
    ]]
    header_table = Table(header_data, colWidths=[doc.width * 0.6, doc.width * 0.4])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), accent_rgb),
        ("TOPPADDING", (0, 0), (-1, -1), 20),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 20),
        ("LEFTPADDING", (0, 0), (-1, -1), 25),
        ("RIGHTPADDING", (0, 0), (-1, -1), 25),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 25))
    
    # Company & Client Info
    cinfo = f"<b>From:</b><br/>{tenant.company_name}<br/>{tenant.company_address or ''}<br/>{tenant.company_email or ''}"
    if tenant.vat_number:
        cinfo += f"<br/>VAT: {tenant.vat_number}"
    
    clinfo = f"<b>Bill To:</b><br/>{invoice.client.name}<br/>{invoice.client.address or ''}<br/><b>Date:</b> {invoice.invoice_date}"
    
    info_table = Table([[Paragraph(cinfo, styles["Normal"]), Paragraph(clinfo, styles["Normal"])]], colWidths=[doc.width/2, doc.width/2])
    info_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(info_table)
    story.append(Spacer(1, 20))
    
    # Items
    items_data = [[
        Paragraph("<b>Description</b>", styles["Normal"]),
        Paragraph("<b>Qty</b>", styles["Normal"]),
        Paragraph("<b>Rate</b>", styles["Normal"]),
        Paragraph("<b>Amount</b>", styles["Normal"])
    ]]
    
    for item in invoice.items:
        items_data.append([
            Paragraph(item.description or '', styles["Normal"]),
            str(item.quantity),
            f"£{item.rate:,.2f}",
            Paragraph(f"<b>£{item.amount:,.2f}</b>", styles["Normal"])
        ])
    
    items_table = Table(items_data, colWidths=[doc.width*0.4, doc.width*0.15, doc.width*0.2, doc.width*0.25])
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), accent_rgb),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (2, -1), "CENTER"),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 20))
    
    # Totals
    totals_data = [
        ["Subtotal", f"£{invoice.subtotal:,.2f}"],
        [f"Tax ({tenant.tax_rate*100:.0f}%)", f"£{invoice.tax_amount:,.2f}"],
        [Paragraph("<b>TOTAL</b>", ParagraphStyle("T", fontSize=14, fontName="Helvetica-Bold")),
         Paragraph(f"<b>£{invoice.total:,.2f}</b>", ParagraphStyle("T", fontSize=14, fontName="Helvetica-Bold"))]
    ]
    totals_table = Table(totals_data, colWidths=[doc.width*0.7, doc.width*0.3])
    totals_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 2), (-1, 2), accent_rgb),
        ("TEXTCOLOR", (0, 2), (-1, 2), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 15),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 30))
    
    if tenant.invoice_footer:
        story.append(Paragraph(f"<i>{tenant.invoice_footer}</i>",
            ParagraphStyle("F", fontSize=9, textColor=colors.gray, alignment=TA_CENTER)))
    
    doc.build(story)
    buffer.seek(0)
    return buffer

# =========================
# ERROR HANDLERS
# =========================
@app.errorhandler(404)
def not_found(error):
    return render_template_string('<h1>404 - Not Found</h1><a href="/">← Home</a>', None), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template_string('<h1>500 - Server Error</h1><a href="/">← Home</a>', None), 500

# =========================
# TEMPLATES
# =========================
PRO_CSS = """
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
    * { margin:0; padding:0; box-sizing:border-box; }
    body { font-family:'Inter',sans-serif; background:#f1f5f9; color:#1e293b; line-height:1.5; }
    .navbar { background:white; border-bottom:1px solid #e2e8f0; padding:12px 24px; display:flex; justify-content:space-between; align-items:center; min-height:60px; flex-wrap:wrap; gap:12px; }
    .navbar-brand { font-size:18px; font-weight:700; color:#0d9488; text-decoration:none; display:flex; align-items:center; gap:8px; }
    .navbar-links { display:flex; gap:6px; align-items:center; flex-wrap:wrap; }
    .navbar-links a { color:#475569; text-decoration:none; padding:6px 12px; border-radius:50px; font-size:13px; font-weight:500; transition:all 0.2s; border:1px solid transparent; }
    .navbar-links a:hover { background:#f1f5f9; border-color:#e2e8f0; }
    .navbar-links a.btn-accent { background:#0d9488; color:white; border-color:#0d9488; }
    .container { max-width:1200px; margin:0 auto; padding:24px 16px; }
    .card { background:white; border-radius:12px; border:1px solid #e2e8f0; padding:24px; box-shadow:0 1px 3px rgba(0,0,0,0.04); }
    .card-title { font-size:18px; font-weight:700; color:#1e293b; margin-bottom:16px; }
    .form-group { margin-bottom:14px; }
    .form-group label { display:block; margin-bottom:4px; font-weight:600; color:#475569; font-size:12px; text-transform:uppercase; letter-spacing:0.5px; }
    .form-group input, .form-group select, .form-group textarea { width:100%; padding:10px 12px; border:1px solid #e2e8f0; border-radius:8px; font-family:inherit; }
    .form-group input:focus, .form-group select:focus, .form-group textarea:focus { outline:none; border-color:#0d9488; box-shadow:0 0 0 3px rgba(13,148,136,0.1); }
    .btn { display:inline-flex; align-items:center; gap:6px; padding:10px 20px; border-radius:50px; font-weight:600; font-size:13px; cursor:pointer; transition:all 0.2s; text-decoration:none; border:none; font-family:inherit; }
    .btn-primary { background:#0d9488; color:white; }
    .btn-primary:hover { background:#0f766e; transform:translateY(-1px); box-shadow:0 4px 12px rgba(13,148,136,0.2); }
    .btn-secondary { background:white; color:#475569; border:1px solid #e2e8f0; }
    .btn-secondary:hover { background:#f8fafc; border-color:#cbd5e1; }
    .btn-danger { background:#ef4444; color:white; }
    .btn-danger:hover { background:#dc2626; }
    .flash { padding:14px 18px; border-radius:10px; margin-bottom:16px; font-size:14px; border-left:4px solid; }
    .flash-success { background:#f0fdf4; border-color:#22c55e; color:#166534; }
    .flash-error { background:#fef2f2; border-color:#ef4444; color:#991b1b; }
    .badge { display:inline-block; padding:4px 14px; border-radius:50px; font-weight:600; font-size:11px; text-transform:uppercase; letter-spacing:0.3px; }
    .badge-success { background:#dcfce7; color:#166534; }
    .badge-warning { background:#fef3c7; color:#92400e; }
    .badge-danger { background:#fee2e2; color:#991b1b; }
    table { width:100%; border-collapse:collapse; }
    th { background:#f8fafc; padding:10px 12px; text-align:left; font-weight:600; color:#475569; font-size:11px; text-transform:uppercase; letter-spacing:0.5px; border-bottom:1px solid #e2e8f0; }
    td { padding:10px 12px; border-bottom:1px solid #f1f5f9; font-size:13px; }
    tr:hover td { background:#f8fafc; }
    .stat-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:24px; }
    @media(max-width:800px) { .stat-grid { grid-template-columns:1fr 1fr; } }
    .stat-card { background:white; border-radius:12px; padding:20px; border:1px solid #e2e8f0; text-align:center; }
    .stat-value { font-size:26px; font-weight:800; color:#0d9488; }
    .stat-label { font-size:11px; color:#64748b; text-transform:uppercase; letter-spacing:0.5px; margin-top:4px; }
</style>
"""

LOGIN_TEMPLATE = f"""
<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Login - Job Diary Pro SaaS</title>{PRO_CSS}
<style>
body{{display:flex;justify-content:center;align-items:center;min-height:100vh;background:linear-gradient(135deg,#0d9488,#0f766e)}}
.login-card{{background:white;border-radius:16px;padding:40px;width:100%;max-width:380px;box-shadow:0 25px 50px rgba(0,0,0,0.15);text-align:center}}
.login-card h1{{font-size:24px;font-weight:800;color:#1e293b;margin-bottom:4px}}
.login-card p{{color:#64748b;margin-bottom:24px;font-size:14px}}
.form-group input{{width:100%;padding:12px 14px;border:2px solid #e2e8f0;border-radius:10px;font-size:14px;margin-bottom:16px;text-align:center}}
.form-group input:focus{{outline:none;border-color:#0d9488}}
.btn{{width:100%;padding:12px;background:#0d9488;color:white;border:none;border-radius:10px;font-weight:600;cursor:pointer;font-size:15px;transition:all 0.2s}}
.btn:hover{{background:#0f766e}}
.signup-link{{margin-top:16px;color:#64748b;font-size:14px}}
.signup-link a{{color:#0d9488;text-decoration:none;font-weight:600}}
</style>
</head><body>
<div class="login-card">
<h1>📋 Job Diary Pro</h1>
<p>Multi-Tenant Business Management</p>
<form method="POST">
<div class="form-group"><input type="email" name="email" placeholder="Email" required autofocus></div>
<div class="form-group"><input type="password" name="password" placeholder="Password" required></div>
<button type="submit" class="btn">🔓 Login</button>
</form>
<div class="signup-link">Don't have an account? <a href="/signup">Sign up</a></div>
</div>
</body></html>
"""

SIGNUP_TEMPLATE = f"""
<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sign Up - Job Diary Pro SaaS</title>{PRO_CSS}
<style>
body{{display:flex;justify-content:center;align-items:center;min-height:100vh;background:linear-gradient(135deg,#0d9488,#0f766e);padding:20px}}
.signup-card{{background:white;border-radius:16px;padding:40px;width:100%;max-width:450px;box-shadow:0 25px 50px rgba(0,0,0,0.15)}}
.signup-card h1{{font-size:24px;font-weight:800;color:#1e293b;margin-bottom:4px;text-align:center}}
.signup-card p{{color:#64748b;margin-bottom:24px;font-size:14px;text-align:center}}
.form-row{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
@media(max-width:600px){{.form-row{{grid-template-columns:1fr}}}}
</style>
</head><body>
<div class="signup-card">
<h1>📋 Join Job Diary Pro</h1>
<p>Start managing your business professionally</p>
<form method="POST">
<div class="form-row">
<div class="form-group"><label>First Name</label><input type="text" name="first_name" required></div>
<div class="form-group"><label>Last Name</label><input type="text" name="last_name" required></div>
</div>
<div class="form-group"><label>Company Name</label><input type="text" name="company_name" required></div>
<div class="form-group"><label>Email</label><input type="email" name="email" required></div>
<div class="form-group"><label>Password</label><input type="password" name="password" required></div>
<button type="submit" class="btn btn-primary" style="width:100%;margin-top:8px">✅ Create Account</button>
</form>
<p style="text-align:center;margin-top:16px;color:#64748b;font-size:14px">Already have an account? <a href="/login" style="color:#0d9488;text-decoration:none;font-weight:600">Login</a></p>
</div>
</body></html>
"""

DASHBOARD_TEMPLATE = f"""
<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dashboard - {{{{ tenant.company_name }}}}</title>{PRO_CSS}</head><body>
<div class="navbar">
<a href="/" class="navbar-brand">📋 {{{{ tenant.company_name }}}}</a>
<div class="navbar-links">
<a href="/jobs">📍 Jobs</a>
<a href="/invoices">💰 Invoices</a>
<a href="/clients">👥 Clients</a>
<a href="/settings">⚙️ Settings</a>
<a href="/billing" class="btn-accent">💳 Billing</a>
<a href="/logout" class="btn-secondary">🚪 Logout</a>
</div>
</div>
<div class="container">
<div class="stat-grid">
<div class="stat-card"><div style="font-size:24px">📍</div><div class="stat-value">{{{{ total_jobs }}}}</div><div class="stat-label">Total Jobs</div></div>
<div class="stat-card"><div style="font-size:24px">⏳</div><div class="stat-value">{{{{ upcoming_jobs }}}}</div><div class="stat-label">Upcoming</div></div>
<div class="stat-card"><div style="font-size:24px">📄</div><div class="stat-value">{{{{ total_invoices }}}}</div><div class="stat-label">Invoices</div></div>
<div class="stat-card"><div style="font-size:24px">💷</div><div class="stat-value">£{{{{ "%.0f"|format(total_revenue) }}}}</div><div class="stat-label">Revenue</div></div>
</div>
<div class="card">
<div class="card-title">📋 Recent Jobs</div>
<table>
<thead><tr><th>Customer</th><th>Date</th><th>Time</th><th>Address</th></tr></thead>
<tbody>
{% for job in recent_jobs %}
<tr><td>{{{{ job.customer }}}}</td><td>{{{{ job.date }}}}</td><td>{{{{ job.time }}}}</td><td>{{{{ job.address }}}}</td></tr>
{% endfor %}
</tbody>
</table>
</div>
<a href="/jobs" class="btn btn-primary" style="margin-top:24px">+ Add New Job</a>
</div>
</body></html>
"""

JOBS_TEMPLATE = f"""
<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Jobs - {{{{ tenant.company_name }}}}</title>{PRO_CSS}</head><body>
<div class="navbar">
<a href="/" class="navbar-brand">📍 Jobs</a>
<div class="navbar-links">
<a href="/">📋 Dashboard</a>
<a href="/invoices">💰 Invoices</a>
<a href="/logout" class="btn-secondary">🚪 Logout</a>
</div>
</div>
<div class="container">
<div class="card">
<div class="card-title">➕ Add New Job</div>
<form method="POST">
<div class="form-group"><label>Customer Name</label><input type="text" name="customer" required></div>
<div class="form-group"><label>Email</label><input type="email" name="email" required></div>
<div class="form-group"><label>Phone</label><input type="tel" name="phone_number" required></div>
<div class="form-group"><label>Description</label><textarea name="description" style="min-height:100px" required></textarea></div>
<div class="form-group"><label>Address</label><input type="text" name="address" required></div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
<div class="form-group"><label>Date</label><input type="date" name="date" required></div>
<div class="form-group"><label>Start Time</label><input type="time" name="time" required></div>
</div>
<div class="form-group"><label>End Time</label><input type="time" name="end_time" required></div>
<button type="submit" class="btn btn-primary" style="width:100%;margin-top:8px">✅ Add Job</button>
</form>
</div>
<div class="card" style="margin-top:24px">
<div class="card-title">📋 All Jobs</div>
<table>
<thead><tr><th>Customer</th><th>Date</th><th>Time</th><th>Address</th><th>Actions</th></tr></thead>
<tbody>
{% for job in jobs %}
<tr>
<td>{{{{ job.customer }}}}</td>
<td>{{{{ job.date }}}}</td>
<td>{{{{ job.time }}}} - {{{{ job.end_time }}}}</td>
<td>{{{{ job.address }}}}</td>
<td><form method="POST" action="/jobs/{{{{ job.id }}}}/delete" style="display:inline"><button type="submit" class="btn btn-danger btn-sm" onclick="return confirm('Delete?')">🗑️</button></form></td>
</tr>
{% endfor %}
</tbody>
</table>
</div>
</div>
</body></html>
"""

INVOICES_TEMPLATE = f"""
<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Invoices - {{{{ tenant.company_name }}}}</title>{PRO_CSS}</head><body>
<div class="navbar">
<a href="/" class="navbar-brand">💰 Invoices</a>
<div class="navbar-links">
<a href="/">📋 Dashboard</a>
<a href="/clients">👥 Clients</a>
<a href="/logout" class="btn-secondary">🚪 Logout</a>
</div>
</div>
<div class="container">
<div class="stat-grid">
<div class="stat-card"><div style="font-size:24px">💷</div><div class="stat-value">£{{{{ "%.0f"|format(analytics.total) }}}}</div><div class="stat-label">Total</div></div>
<div class="stat-card"><div style="font-size:24px">✅</div><div class="stat-value" style="color:#22c55e">£{{{{ "%.0f"|format(analytics.paid) }}}}</div><div class="stat-label">Paid</div></div>
<div class="stat-card"><div style="font-size:24px">⏳</div><div class="stat-value" style="color:#f59e0b">£{{{{ "%.0f"|format(analytics.unpaid) }}}}</div><div class="stat-label">Unpaid</div></div>
<div class="stat-card"><div style="font-size:24px">⚠️</div><div class="stat-value" style="color:#ef4444">£{{{{ "%.0f"|format(analytics.overdue) }}}}</div><div class="stat-label">Overdue</div></div>
</div>
<div class="card">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
<div class="card-title">📄 All Invoices</div>
<a href="/invoices/create" class="btn btn-primary btn-sm">+ New Invoice</a>
</div>
<table>
<thead><tr><th>Invoice #</th><th>Client</th><th>Amount</th><th>Status</th><th>Actions</th></tr></thead>
<tbody>
{% for invoice in invoices %}
<tr>
<td><strong>{{{{ invoice.invoice_number }}}}</strong></td>
<td>{{{{ invoice.client.name }}}}</td>
<td>£{{{{ "%.2f"|format(invoice.total) }}}}</td>
<td><span class="badge badge-{{'success' if invoice.status=='paid' else 'warning' if invoice.status=='unpaid' else 'danger'}}">{{{{ invoice.status }}}}</span></td>
<td><a href="/invoices/{{{{ invoice.id }}}}" class="btn btn-secondary btn-sm">View</a> <a href="/invoices/{{{{ invoice.id }}}}/pdf" class="btn btn-secondary btn-sm">PDF</a></td>
</tr>
{% endfor %}
</tbody>
</table>
</div>
</div>
</body></html>
"""

CREATE_INVOICE_TEMPLATE = f"""
<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Create Invoice</title>{PRO_CSS}</head><body>
<div class="navbar">
<a href="/invoices" class="navbar-brand">📄 New Invoice</a>
<div class="navbar-links"><a href="/invoices">← Back</a></div>
</div>
<div class="container">
<div class="card" style="max-width:700px;margin:0 auto">
<div class="card-title">Create Invoice</div>
<form method="POST">
<div class="form-group"><label>Client</label><select name="client_id" required>
{{% for client in clients %}}<option value="{{{{ client.id }}}}">{{{{ client.name }}}}</option>{{% endfor %}}
</select></div>
<div class="form-group"><label>Line Items</label><div id="items" style="display:grid;gap:8px">
<div style="display:grid;grid-template-columns:2fr 1fr 1fr;gap:8px">
<input type="text" name="descriptions[]" placeholder="Description" required>
<input type="number" name="quantities[]" placeholder="Qty" step="0.01" required>
<input type="number" name="rates[]" placeholder="Rate" step="0.01" required>
</div>
</div></div>
<button type="button" class="btn btn-secondary btn-sm" onclick="addItem()" style="margin-bottom:12px">+ Add Item</button>
<button type="submit" class="btn btn-primary" style="width:100%">Generate Invoice</button>
</form>
</div>
</div>
<script>
function addItem(){{
const d=document.createElement('div');
d.style='display:grid;grid-template-columns:2fr 1fr 1fr;gap:8px';
d.innerHTML='<input type="text" name="descriptions[]" placeholder="Description" required><input type="number" name="quantities[]" placeholder="Qty" step="0.01" required><input type="number" name="rates[]" placeholder="Rate" step="0.01" required>';
document.getElementById('items').appendChild(d);
}}
</script>
</body></html>
"""

INVOICE_DETAIL_TEMPLATE = f"""
<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Invoice {{{{ invoice.invoice_number }}}}</title>{PRO_CSS}
<style>
.inv-card{{max-width:800px;margin:0 auto;background:white;border-radius:12px;overflow:hidden;border:1px solid #e2e8f0}}
.inv-header{{background:#0d9488;color:white;padding:32px;display:flex;justify-content:space-between;align-items:center}}
.inv-body{{padding:32px}}
.totals{{text-align:right;padding:20px;background:#f8fafc;border-radius:10px;margin-top:20px}}
.total-row{{display:flex;justify-content:flex-end;gap:32px;padding:6px 0;font-size:14px}}
.total-grand{{font-size:20px;font-weight:700;color:#0d9488;margin-top:10px;padding-top:10px;border-top:2px solid #e2e8f0}}
</style>
</head><body>
<div class="navbar"><a href="/invoices" class="navbar-brand">Invoice {{{{ invoice.invoice_number }}}}</a><div class="navbar-links"><a href="/invoices">← Back</a></div></div>
<div class="container">
<div class="inv-card">
<div class="inv-header"><h1>INVOICE #{{{{ invoice.invoice_number }}}}</h1></div>
<div class="inv-body">
<div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-bottom:24px;padding-bottom:24px;border-bottom:1px solid #e2e8f0">
<div>
<h3 style="font-size:11px;text-transform:uppercase;color:#64748b;letter-spacing:0.5px;margin-bottom:8px">From</h3>
<p><strong>{{{{ tenant.company_name }}}}</strong><br>{{{{ tenant.company_address }}}}<br>{{{{ tenant.company_email }}}}</p>
</div>
<div>
<h3 style="font-size:11px;text-transform:uppercase;color:#64748b;letter-spacing:0.5px;margin-bottom:8px">Bill To</h3>
<p><strong>{{{{ invoice.client.name }}}}</strong><br>{{{{ invoice.client.address }}}}</p>
</div>
</div>
<table>
<thead><tr><th>Description</th><th>Qty</th><th>Rate</th><th>Amount</th></tr></thead>
<tbody>
{{% for item in invoice.items %}}
<tr><td>{{{{ item.description }}}}</td><td>{{{{ item.quantity }}}}</td><td>£{{{{ "%.2f"|format(item.rate) }}}}</td><td><strong>£{{{{ "%.2f"|format(item.amount) }}}}</strong></td></tr>
{{% endfor %}}
</tbody>
</table>
<div class="totals">
<div class="total-row"><span>Subtotal:</span><span>£{{{{ "%.2f"|format(invoice.subtotal) }}}}</span></div>
<div class="total-row"><span>Tax:</span><span>£{{{{ "%.2f"|format(invoice.tax_amount) }}}}</span></div>
<div class="total-row total-grand"><span>TOTAL:</span><span>£{{{{ "%.2f"|format(invoice.total) }}}}</span></div>
</div>
<div style="display:flex;gap:8px;margin-top:20px">
<a href="/invoices/{{{{ invoice.id }}}}/pdf" class="btn btn-primary">📥 PDF</a>
<form method="POST" action="/invoices/{{{{ invoice.id }}}}/delete" style="display:inline"><button type="submit" class="btn btn-danger" onclick="return confirm('Delete?')">🗑️ Delete</button></form>
</div>
</div>
</div>
</div>
</body></html>
"""

CLIENTS_TEMPLATE = f"""
<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Clients</title>{PRO_CSS}</head><body>
<div class="navbar">
<a href="/" class="navbar-brand">👥 Clients</a>
<div class="navbar-links">
<a href="/">📋 Dashboard</a>
<a href="/invoices">💰 Invoices</a>
<a href="/logout" class="btn-secondary">🚪 Logout</a>
</div>
</div>
<div class="container">
<div class="card">
<div class="card-title">➕ Add New Client</div>
<form method="POST">
<div class="form-group"><label>Name</label><input type="text" name="name" required></div>
<div class="form-group"><label>Company</label><input type="text" name="company_name"></div>
<div class="form-group"><label>Email</label><input type="email" name="email" required></div>
<div class="form-group"><label>Phone</label><input type="tel" name="phone" required></div>
<div class="form-group"><label>Address</label><textarea name="address" style="min-height:80px"></textarea></div>
<button type="submit" class="btn btn-primary" style="width:100%;margin-top:8px">✅ Add Client</button>
</form>
</div>
<div class="card" style="margin-top:24px">
<div class="card-title">📋 All Clients</div>
<table>
<thead><tr><th>Name</th><th>Company</th><th>Email</th><th>Phone</th><th>Actions</th></tr></thead>
<tbody>
{% for client in clients %}
<tr>
<td>{{{{ client.name }}}}</td>
<td>{{{{ client.company_name }}}}</td>
<td>{{{{ client.email }}}}</td>
<td>{{{{ client.phone }}}}</td>
<td><form method="POST" action="/clients/{{{{ client.id }}}}/delete" style="display:inline"><button type="submit" class="btn btn-danger btn-sm" onclick="return confirm('Delete?')">🗑️</button></form></td>
</tr>
{% endfor %}
</tbody>
</table>
</div>
</div>
</body></html>
"""

SETTINGS_TEMPLATE = f"""
<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Settings</title>{PRO_CSS}</head><body>
<div class="navbar">
<a href="/" class="navbar-brand">⚙️ Settings</a>
<div class="navbar-links"><a href="/">← Dashboard</a><a href="/logout" class="btn-secondary">🚪 Logout</a></div>
</div>
<div class="container">
<div class="card" style="max-width:700px;margin:0 auto">
<div class="card-title">Company Settings</div>
<form method="POST">
<div class="form-group"><label>Company Email</label><input type="email" name="company_email" value="{{{{ tenant.company_email or '' }}}}"></div>
<div class="form-group"><label>Phone</label><input type="tel" name="company_phone" value="{{{{ tenant.company_phone or '' }}}}"></div>
<div class="form-group"><label>Address</label><textarea name="company_address">{{{{ tenant.company_address or '' }}}}</textarea></div>
<div class="form-group"><label>VAT Number</label><input type="text" name="vat_number" value="{{{{ tenant.vat_number or '' }}}}"></div>
<div class="form-group"><label>Tax Rate</label><input type="number" step="0.01" name="tax_rate" value="{{{{ tenant.tax_rate }}}}"></div>
<div class="form-group"><label>Brand Color</label><input type="color" name="accent_color" value="{{{{ tenant.accent_color }}}}"></div>
<div class="form-group"><label>Invoice Footer</label><textarea name="invoice_footer">{{{{ tenant.invoice_footer or 'Thank you for your business!' }}}}</textarea></div>
<button type="submit" class="btn btn-primary" style="width:100%;margin-top:8px">💾 Save Settings</button>
</form>
</div>
</div>
</body></html>
"""

BILLING_TEMPLATE = f"""
<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Billing</title>{PRO_CSS}</head><body>
<div class="navbar">
<a href="/" class="navbar-brand">💳 Billing</a>
<div class="navbar-links"><a href="/">← Dashboard</a><a href="/logout" class="btn-secondary">🚪 Logout</a></div>
</div>
<div class="container">
<div class="card" style="max-width:700px;margin:0 auto">
<div class="card-title">Subscription Plans</div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-top:20px">
<div style="border:1px solid #e2e8f0;padding:20px;border-radius:12px;text-align:center">
<h3>Free</h3>
<p style="font-size:24px;font-weight:700;color:#0d9488">£0</p>
<p style="color:#64748b;font-size:13px;margin:10px 0">5 Invoices/Month<br>1 User<br>Basic Support</p>
<button class="btn btn-secondary" style="width:100%;margin-top:10px" {{'disabled' if tenant.subscription_plan=='free' else ''}}>{{{{ 'Current Plan' if tenant.subscription_plan=='free' else 'Upgrade' }}}}</button>
</div>
<div style="border:2px solid #0d9488;padding:20px;border-radius:12px;text-align:center">
<h3>Pro</h3>
<p style="font-size:24px;font-weight:700;color:#0d9488">£29<span style="font-size:13px">/mo</span></p>
<p style="color:#64748b;font-size:13px;margin:10px 0">Unlimited Invoices<br>5 Users<br>Priority Support</p>
<button class="btn btn-primary" style="width:100%;margin-top:10px" {{'disabled' if tenant.subscription_plan=='pro' else ''}}>{{{{ 'Current Plan' if tenant.subscription_plan=='pro' else 'Upgrade' }}}}</button>
</div>
<div style="border:1px solid #e2e8f0;padding:20px;border-radius:12px;text-align:center">
<h3>Enterprise</h3>
<p style="font-size:24px;font-weight:700;color:#0d9488">Custom</p>
<p style="color:#64748b;font-size:13px;margin:10px 0">Everything in Pro<br>Unlimited Users<br>Dedicated Support</p>
<button class="btn btn-secondary" style="width:100%;margin-top:10px">Contact Sales</button>
</div>
</div>
</div>
</div>
</body></html>
"""

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
