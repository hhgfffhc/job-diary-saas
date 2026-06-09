"""
Background tasks for Job Diary Pro SaaS
Handles emails, reminders, PDF generation, etc.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from io import BytesIO

from app import celery, app, db
from app import Job, Invoice, Tenant, User

def send_email(to_email, subject, body):
    """Send email via SMTP"""
    try:
        from_email = app.config['MAIL_USERNAME']
        password = app.config['MAIL_PASSWORD']
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"Job Diary Pro <{from_email}>"
        msg['To'] = to_email
        
        # HTML version
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: 'Segoe UI', sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #0d9488; color: white; padding: 30px; border-radius: 10px 10px 0 0; text-align: center; }}
                .content {{ background: #f8fafc; padding: 30px; border-radius: 0 0 10px 10px; }}
                .btn {{ display: inline-block; background: #0d9488; color: white; padding: 10px 20px; border-radius: 5px; text-decoration: none; }}
                .footer {{ font-size: 12px; color: #64748b; margin-top: 20px; text-align: center; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header"><h1>📋 Job Diary Pro</h1></div>
                <div class="content">
                    {body.replace(chr(10), '<br>')}
                </div>
                <div class="footer">
                    <p>© 2024 Job Diary Pro. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        part1 = MIMEText(body, 'plain')
        part2 = MIMEText(html, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        # Send via SMTP
        server = smtplib.SMTP(app.config['MAIL_SERVER'], app.config['MAIL_PORT'])
        server.starttls()
        server.login(from_email, password)
        server.send_message(msg)
        server.quit()
        
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

def check_24h_reminders():
    """Check for jobs happening in 24 hours and send reminders"""
    try:
        now = datetime.utcnow()
        tomorrow_start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_end = (tomorrow_start + timedelta(days=1)).replace(hour=23, minute=59, second=59)
        
        # Find jobs for tomorrow that haven't been notified
        jobs = Job.query.filter(
            Job.date == tomorrow_start.date(),
            Job.notified_24h == False,
            Job.email != None
        ).all()
        
        for job in jobs:
            try:
                body = f"""
                Hello {job.customer},
                
                Reminder: You have a job scheduled for tomorrow!
                
                📅 Date: {job.date}
                🕐 Time: {job.time} - {job.end_time or 'TBD'}
                📍 Location: {job.address}
                📋 Description: {job.description}
                
                If you need to reschedule or have any questions, please contact us.
                
                Best regards,
                Job Diary Pro Team
                """
                
                send_email(job.email, f"🚨 Job Reminder - {job.customer}", body)
                job.notified_24h = True
                db.session.commit()
            except Exception as e:
                print(f"Reminder error for job {job.id}: {e}")
        
        return len(jobs)
    except Exception as e:
        print(f"24h reminders error: {e}")
        return 0

def send_invoice_notification(invoice_id, customer_email, action='created'):
    """Send invoice notification email"""
    try:
        invoice = Invoice.query.get(invoice_id)
        if not invoice:
            return False
        
        tenant = invoice.tenant
        
        if action == 'created':
            subject = f"📄 Invoice {invoice.invoice_number} Created"
            body = f"""
            Hello {invoice.client.name},
            
            Your invoice has been created and is ready for review.
            
            Invoice Details:
            - Invoice #: {invoice.invoice_number}
            - Date: {invoice.invoice_date}
            - Due Date: {invoice.due_date}
            - Total: £{invoice.total:,.2f}
            
            Please review the attached invoice. If you have any questions, feel free to reach out.
            
            Best regards,
            {tenant.company_name}
            """
        
        elif action == 'sent':
            subject = f"📄 Invoice {invoice.invoice_number} - Payment Due"
            body = f"""
            Hello {invoice.client.name},
            
            We've sent you an invoice for services rendered.
            
            Invoice #: {invoice.invoice_number}
            Amount: £{invoice.total:,.2f}
            Due Date: {invoice.due_date}
            
            Please arrange payment at your earliest convenience. Contact us if you need any clarification.
            
            Best regards,
            {tenant.company_name}
            """
        
        elif action == 'paid':
            subject = f"✅ Invoice {invoice.invoice_number} - Payment Received"
            body = f"""
            Hello,
            
            Thank you! We've received your payment for invoice {invoice.invoice_number}.
            
            Amount: £{invoice.total:,.2f}
            Date Received: {datetime.utcnow().strftime('%Y-%m-%d')}
            
            Your account is now up to date. We appreciate your business!
            
            Best regards,
            {tenant.company_name}
            """
        
        return send_email(customer_email, subject, body)
    
    except Exception as e:
        print(f"Invoice notification error: {e}")
        return False

def generate_invoice_pdf(invoice_id):
    """Generate PDF for invoice (used by main app)"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_LEFT, TA_CENTER
    
    try:
        invoice = Invoice.query.get(invoice_id)
        if not invoice:
            return None
        
        tenant = invoice.tenant
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=50, leftMargin=50, topMargin=30, bottomMargin=50)
        styles = getSampleStyleSheet()
        story = []
        
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
    
    except Exception as e:
        print(f"PDF generation error: {e}")
        return None

@celery.task
def send_email_async(to_email, subject, body):
    """Async email sending"""
    return send_email(to_email, subject, body)

@celery.task
def send_invoice_notification_async(invoice_id, customer_email, action='created'):
    """Async invoice notification"""
    return send_invoice_notification(invoice_id, customer_email, action)

@celery.task
def check_24h_reminders_async():
    """Async 24h reminder check"""
    return check_24h_reminders()

@celery.task
def check_overdue_invoices():
    """Check and mark overdue invoices"""
    try:
        from app import Invoice
        
        today = datetime.utcnow().date()
        invoices = Invoice.query.filter(
            Invoice.status.in_(['unpaid', 'sent']),
            Invoice.due_date < today
        ).all()
        
        for invoice in invoices:
            invoice.status = 'overdue'
        
        db.session.commit()
        return len(invoices)
    except Exception as e:
        print(f"Overdue check error: {e}")
        return 0
