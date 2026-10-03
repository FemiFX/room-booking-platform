import os
from functools import wraps

import requests
from flask import Flask, render_template, request, redirect, url_for, jsonify, Response
from flask_mail import Mail, Message
from flask_cors import CORS
from random import randint
import random
import mysql.connector
import smtplib
import json
from datetime import datetime, timedelta, time
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt  # Flask-Bcrypt handles password hashing and checking

app = Flask(__name__)
CORS(app)

# Initialize Flask-Login and Flask-Bcrypt
login_manager = LoginManager()
login_manager.init_app(app)
bcrypt = Bcrypt(app)
login_manager.login_view = 'login'  # Redirect to login page if not logged in

def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# --- Secrets and configuration -------------------------------------------
# Everything comes from the environment. An earlier revision hardcoded the
# session key, the SMTP password and the database password directly in this
# file; see the README.
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-only-insecure-key')

if os.environ.get('FLASK_ENV') == 'production' and \
        app.config['SECRET_KEY'] == 'dev-only-insecure-key':
    raise RuntimeError(
        "SECRET_KEY must be set in production. Refusing to start on the "
        "development default -- it would let anyone forge a session cookie."
    )

# --- Branding -------------------------------------------------------------
app.config['BRAND_NAME'] = os.environ.get('BRAND_NAME', 'Room Booking')
app.config['BRAND_LOGO'] = os.environ.get('BRAND_LOGO', 'images/logo.png')


@app.context_processor
def inject_branding():
    return {
        'brand_name': app.config['BRAND_NAME'],
        'brand_logo': app.config['BRAND_LOGO'],
    }


# --- Mail -----------------------------------------------------------------
# Optional. With MAIL_ENABLED off, notification emails are logged instead of
# sent, so the whole booking flow works with no SMTP server.
app.config['MAIL_ENABLED'] = _env_bool('MAIL_ENABLED', False)
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'localhost')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', '587'))
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_USE_TLS'] = _env_bool('MAIL_USE_TLS', True)
app.config['MAIL_USE_SSL'] = _env_bool('MAIL_USE_SSL', False)
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get(
    'MAIL_DEFAULT_SENDER', 'no-reply@example.com'
)
app.config['ADMIN_EMAIL'] = os.environ.get('ADMIN_EMAIL', 'admin@example.com')

mail = Mail(app)


def send_mail(subject, recipients, body=None, html=None):
    """Send a message, or log it when mail is disabled.

    Mail is optional on purpose: the booking flow is fully usable without an
    SMTP server, which is what makes this runnable from a fresh clone. A send
    failure is logged rather than raised -- a booking already committed to the
    database must not 500 because a mail server was unreachable.
    """
    if not app.config['MAIL_ENABLED']:
        app.logger.info(
            "[mail disabled] to=%s subject=%s", ", ".join(recipients), subject
        )
        return False
    try:
        msg = Message(subject, recipients=recipients)
        if body:
            msg.body = body
        if html:
            msg.html = html
        mail.send(msg)
        return True
    except Exception as exc:
        app.logger.warning("mail send failed (subject=%r): %s", subject, exc)
        return False


def admin_required(view):
    """Reject non-admins. Applied under @login_required."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            return "Access denied", 403
        return view(*args, **kwargs)
    return wrapper


# --- Database -------------------------------------------------------------
db_config = {
    'user': os.environ.get('DB_USER', 'booking'),
    'password': os.environ.get('DB_PASSWORD', 'booking'),
    'host': os.environ.get('DB_HOST', 'db'),
    'port': int(os.environ.get('DB_PORT', '3306')),
    'database': os.environ.get('DB_NAME', 'booking_app'),
}

# Connect to MySQL database
def get_db_connection():
    return mysql.connector.connect(**db_config)

@app.route('/')
def form():
    # Fetch available resources from the database dynamically
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT name FROM resources")
    resources = cursor.fetchall()  # Get the list of available resources
    cursor.close()
    conn.close()

    # Services can still be hardcoded or fetched dynamically later
    services = ["Technician", "Usher"]

    # Pass the resources and services from the database to the booking form template
    return render_template('booking_form.html', resources=resources, services=services)


@app.route('/submit', methods=['POST'])
def submit_form():
    # Generate a random 6-digit booking number
    booking_number = randint(100000, 999999)

    # Gather form data
    personal_details = {
        "first_name": request.form.get("first_name"),
        "last_name": request.form.get("last_name"),
        "academic_title": request.form.get("academic_title"),
        "organization": request.form.get("organization"),
        "email": request.form.get("email"),
        "address": request.form.get("address")
    }
    
    event_title = request.form.get("event_title")
    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date")
    full_day = request.form.get("full_day")  # Checkbox value
    start_time = "00:00:00" if full_day else request.form.get("start_time") or "00:00:00"
    end_time = "23:59:59" if full_day else request.form.get("end_time") or "23:59:59"
    selected_resource = request.form.get("resource")
    contact_person = request.form.get("contact_person")
    participants = request.form.get("participants")
    billing_info = request.form.get("billing_info")
    additional_info = request.form.get("additional_info")

    # Services
    services = request.form.getlist("services[]")
    cleaning_charge = request.form.get("cleaning_charge")
    services_selected = ', '.join(services)

    # Inventory-Items
    inventory_items_json = request.form.get('inventory_items')
    inventory_items = json.loads(inventory_items_json) if inventory_items_json else []

    # Prepare inventory data for insertion into the database (if you need to store it as text)
    inventory_str = ', '.join([f"{item['name']}: {item['quantity']}" for item in inventory_items])

    # Connect to MySQL
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if the resource is already booked during the selected timeframe
    cursor.execute("""
        SELECT * FROM bookings 
        WHERE resource = %s 
        AND (
            (start_date <= %s AND end_date >= %s) OR
            (start_date <= %s AND end_date >= %s)
        )
        AND (
            (start_time <= %s AND end_time >= %s) OR
            (start_time <= %s AND end_time >= %s)
        )
    """, (selected_resource, end_date, start_date, start_date, end_date, end_time, start_time, start_time, end_time))

    existing_booking = cursor.fetchone()

    if existing_booking:
        cursor.close()
        conn.close()

        # Re-render form with error and pass resources and services again
        return render_template(
            'booking_form.html', 
            resources=get_available_resources(),  # Re-fetch resources here
            services=get_available_services(),    # Re-fetch services here
            error="This resource is already booked during the selected timeframe. Please choose a different time or resource.",
            personal_details=personal_details,
            event_title=event_title,
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time,
            selected_resource=selected_resource,
            contact_person=contact_person,
            participants=participants,
            billing_info=billing_info,
            additional_info=additional_info,
            services_selected=services_selected
        )

    # Proceed with booking if no conflict
    cursor.execute("""
        INSERT INTO bookings (booking_number, first_name, last_name, academic_title, organization, email, address, 
                              event_title, start_date, start_time, end_date, end_time, resource, participants, 
                              billing_info, cleaning_charge, additional_info, contact_person, services, inventory_items)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        booking_number, personal_details['first_name'], personal_details['last_name'], personal_details['academic_title'],
        personal_details['organization'], personal_details['email'], personal_details['address'], event_title,
        start_date, start_time, end_date, end_time, selected_resource, participants, billing_info, cleaning_charge, additional_info, 
        contact_person, services_selected, inventory_str
    ))

    conn.commit()
    cursor.close()
    conn.close()

    # Render the custom HTML email template and pass the necessary data
    email_body = render_template(
        'booking_confirmation_email.html',  # Your custom HTML email template
        first_name=personal_details['first_name'],
        last_name=personal_details['last_name'],
        event_title=event_title,
        start_date=start_date,
        end_date=end_date,
        start_time=start_time,
        end_time=end_time,
        selected_resource=selected_resource,
        participants=participants,
        contact_person=contact_person,
        additional_info=additional_info,
        services_selected=services_selected,
        booking_number=booking_number,
        cleaning_charge=cleaning_charge
    )

    # Send confirmation email to the inquirer with HTML content
    send_mail("Your Booking Inquiry Has Been Received",
              [personal_details['email']], html=email_body)

    # Send email to the admin
    admin_email = app.config["ADMIN_EMAIL"]
    msg_admin = Message("New Booking Inquiry", recipients=[admin_email])
    msg_admin.body = f"""
    New Booking Inquiry

    Personal Details:
    Name: {personal_details['first_name']} {personal_details['last_name']}
    Email: {personal_details['email']}

    Event Details:
    Title: {event_title}
    Start Date: {start_date} {start_time if start_time else '(Whole day)'}
    End Date: {end_date} {end_time if end_time else '(Whole day)'}

    Resource: {selected_resource}
    Contact Person: {contact_person}
    Expected Participants: {participants}

    Additional Info: {additional_info}
    Services: {', '.join(services)}

    Booking Number: {booking_number}
    Cleaning Charge: €{cleaning_charge}
    """
    send_mail("New Booking Inquiry", [admin_email], body=msg_admin.body)

    # Pass booking_number to the confirmation page
    return render_template('confirmation_page.html', booking_number=booking_number)

from datetime import timedelta

# Helper function to convert timedelta to a string
def timedelta_to_string(td):
    """Convert a timedelta object to a string formatted as HH:MM:SS."""
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"

@app.route('/get_inventory', methods=['POST'])
def get_inventory():
    resource = request.json.get('resource')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch the correct resource ID based on the resource name
    cursor.execute("SELECT id FROM resources WHERE name = %s", (resource,))
    resource_id = cursor.fetchone()

    if resource_id:
        # Fetch inventory items for the selected resource ID
        cursor.execute("""
            SELECT inventory.name, inventory.max_quantity 
            FROM inventory
            WHERE inventory.resource_id = %s
        """, (resource_id['id'],))

        inventory_items = cursor.fetchall()

        # Fetch the cleaning charge for the resource
        cursor.execute("SELECT cleaning_charge FROM resources WHERE id = %s", (resource_id['id'],))
        cleaning_charge = cursor.fetchone()['cleaning_charge']
        
        # Fetch the booked times for the selected resource
        cursor.execute("""
            SELECT start_date, start_time, end_date, end_time 
            FROM bookings 
            WHERE resource = %s AND end_date >= NOW()
        """, (resource,))
        
        bookings = cursor.fetchall()

        # Convert timedelta objects (start_time, end_time) to string format
        for booking in bookings:
            if isinstance(booking['start_time'], timedelta):
                booking['start_time'] = timedelta_to_string(booking['start_time'])
            if isinstance(booking['end_time'], timedelta):
                booking['end_time'] = timedelta_to_string(booking['end_time'])

        cursor.close()
        conn.close()

        # Send the inventory items, cleaning charge, and bookings in the response
        return jsonify({
            'inventory': inventory_items, 
            'cleaning_charge': cleaning_charge,
            'bookings': bookings
        })
    else:
        cursor.close()
        conn.close()
        return jsonify({'inventory': [], 'cleaning_charge': 0, 'bookings': []})


@app.route('/retrieve_booking', methods=['GET', 'POST'])
def retrieve_booking():
    if request.method == 'POST':
        booking_number = request.form.get('booking_number')

        # Fetch the booking from the database
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM bookings WHERE booking_number = %s", (booking_number,))
        booking = cursor.fetchone()
        cursor.close()
        conn.close()

        if booking:
            # Function to parse inventory items from the stored string
            def parse_inventory(inventory_str):
                inventory_list = []
                if inventory_str:
                    items = inventory_str.split(', ')
                    for item in items:
                        name, quantity = item.split(': ')
                        inventory_list.append({'name': name, 'quantity': int(quantity)})
                return inventory_list

            # Attach parsed inventory to the booking object
            booking['inventory'] = parse_inventory(booking['inventory_items']) if booking['inventory_items'] else []
            # Split services into a list
            booking['services'] = booking['services'].split(', ')

            # Render the view booking form with the populated data
            return render_template('view_booking.html', 
                                   booking=booking, 
                                   services=get_available_services(), 
                                   resources=get_available_resources())

    return render_template('retrieve_booking.html')


def get_inventory_from_db(resource):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT inventory.name, inventory.max_quantity 
        FROM inventory
        JOIN resources ON resources.id = inventory.resource_id
        WHERE resources.name = %s
    """, (resource,))
    inventory_items = cursor.fetchall()
    cursor.close()
    conn.close()

    return inventory_items

def get_available_services():
    return ["Technician", "Usher"]

def get_available_resources():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT name FROM resources")
    resources = cursor.fetchall()
    cursor.close()
    conn.close()
    return resources

# Function to send modification email
def send_modification_email(personal_details, booking_details):
    email_body = render_template(
        'modification_email.html',  # Use the modification email template
        first_name=personal_details['first_name'],
        last_name=personal_details['last_name'],
        event_title=booking_details['event_title'],
        selected_resource=booking_details['resource'],
        participants=booking_details['participants'],
        start_date=booking_details['start_date'],
        end_date=booking_details['end_date'],
        start_time=booking_details['start_time'],
        end_time=booking_details['end_time'],
        contact_person=booking_details['contact_person'],
        additional_info=booking_details['additional_info'],
        inventory_details=booking_details['inventory_items'],
        services_selected=booking_details['services'],
        booking_number=booking_details['booking_number']
    )
    send_mail("Booking Modification Notification",
              [personal_details['email']], html=email_body)

# Updated modify_booking function
@app.route('/modify_booking/<int:booking_number>', methods=['GET', 'POST'])
def modify_booking(booking_number):
    # Fetch the booking from the database
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM bookings WHERE booking_number = %s", (booking_number,))
    booking = cursor.fetchone()
    cursor.close()
    conn.close()

    if not booking:
        return "Booking not found.", 404

    # Parse inventory items for GET request
    def parse_inventory(inventory_str):
        inventory_list = []
        if inventory_str:
            items = inventory_str.split(', ')
            for item in items:
                name, quantity = item.split(': ')
                inventory_list.append({'name': name, 'quantity': int(quantity)})
        return inventory_list

    # Attach parsed inventory and services to the booking object
    booking['inventory'] = parse_inventory(booking['inventory_items']) if booking['inventory_items'] else []
    booking['services'] = booking['services'].split(', ') if booking['services'] else []

    if request.method == 'POST':
        # Retrieve modified fields
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        academic_title = request.form.get('academic_title')
        organization = request.form.get('organization')
        email = request.form.get('email')
        address = request.form.get('address')
        event_title = request.form.get('event_title')
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')

        if request.form.get("full_day"):
            start_time = "00:00:00"
            end_time = "23:59:59"
        else:
            start_time = request.form.get("start_time") or "00:00:00"
            end_time = request.form.get("end_time") or "23:59:59"

        resource = request.form.get('resource')
        participants = request.form.get('participants')
        billing_info = request.form.get('billing_info')
        additional_info = request.form.get('additional_info')
        contact_person = request.form.get('contact_person')
        cleaning_charge = request.form.get('cleaning_charge')

        # Handle updated inventory items
        updated_inventory = []
        for item in booking['inventory']:
            quantity = request.form.get(f"inventory_{item['name']}")
            updated_inventory.append(f"{item['name']}: {quantity}")

        # Join the updated inventory into a comma-separated string
        inventory_items_str = ', '.join(updated_inventory)

        # Handle updated services (assuming services are checkboxes)
        services = request.form.getlist('services[]')
        services_str = ', '.join(services)

        # Update the booking in the database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE bookings
            SET first_name = %s, last_name = %s, academic_title = %s, organization = %s, email = %s, address = %s,
                event_title = %s, start_date = %s, start_time = %s, end_date = %s, end_time = %s, resource = %s, 
                participants = %s, billing_info = %s, cleaning_charge = %s, additional_info = %s, contact_person = %s, 
                inventory_items = %s, services = %s
            WHERE booking_number = %s
        """, (
            first_name, last_name, academic_title, organization, email, address, event_title,
            start_date, start_time, end_date, end_time, resource, participants, billing_info, cleaning_charge, 
            additional_info, contact_person, inventory_items_str, services_str, booking_number
        ))
        conn.commit()
        cursor.close()
        conn.close()

        # Update the booking object for the email
        booking['first_name'] = first_name
        booking['last_name'] = last_name
        booking['academic_title'] = academic_title
        booking['organization'] = organization
        booking['email'] = email
        booking['address'] = address
        booking['event_title'] = event_title
        booking['start_date'] = start_date
        booking['end_date'] = end_date
        booking['start_time'] = start_time
        booking['end_time'] = end_time
        booking['resource'] = resource
        booking['participants'] = participants
        booking['billing_info'] = billing_info
        booking['additional_info'] = additional_info
        booking['contact_person'] = contact_person
        booking['cleaning_charge'] = cleaning_charge
        booking['inventory'] = parse_inventory(inventory_items_str)
        booking['services'] = services_str.split(', ')

        # Send modification email
        personal_details = {
            "first_name": first_name,
            "last_name": last_name,
            "email": email
        }
        send_modification_email(personal_details, booking)

        return redirect(url_for('modification_confirmation', booking_number=booking_number))

    # Render form for GET request
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT name FROM resources")
    resources = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('view_booking.html', 
                           booking=booking, 
                           resources=resources,
                           services=get_available_services())

@app.route('/modification_confirmation/<int:booking_number>')
def modification_confirmation(booking_number):
    return render_template('modification_confirmation.html', booking_number=booking_number)


# Function to send cancellation email
def send_cancellation_notification(personal_details, booking_details):
    email_body = render_template(
        'cancellation_email.html',  # Use the cancellation email template
        first_name=personal_details['first_name'],
        last_name=personal_details['last_name'],
        event_title=booking_details['event_title'],
        selected_resource=booking_details['resource'],
        start_date=booking_details['start_date'],
        end_date=booking_details['end_date'],
        booking_number=booking_details['booking_number']
    )
    send_mail("Booking Cancellation Notification",
              [personal_details['email']], html=email_body)

# Updated cancel_user_booking function
# Requires login: the body reads current_user.email to prove ownership, which
# raises on an anonymous user rather than denying cleanly.
@app.route('/cancel_user_booking/<int:booking_number>', methods=['POST'])
@login_required
def cancel_user_booking(booking_number):
    # Connect to the database
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Check if the booking belongs to the current user
    cursor.execute("SELECT * FROM bookings WHERE booking_number = %s AND email = %s", 
                   (booking_number, current_user.email))
    booking = cursor.fetchone()

    if booking:
        # Delete the booking if found
        cursor.execute("DELETE FROM bookings WHERE booking_number = %s", (booking_number,))
        conn.commit()
        cursor.close()
        conn.close()

        # Send cancellation email
        personal_details = {
            "first_name": booking['first_name'],
            "last_name": booking['last_name'],
            "email": booking['email']
        }
        send_cancellation_notification(personal_details, booking)

        return redirect(url_for('form'))  # Redirect to the booking form or a success page
    else:
        cursor.close()
        conn.close()
        return "You do not have permission to cancel this booking.", 403

from datetime import timedelta, time

# Helper function to convert timedelta to time
def timedelta_to_time(td):
    """Convert a timedelta object to a time object."""
    seconds = int(td.total_seconds())
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return time(hour=hours, minute=minutes, second=seconds)

# Calendar colours, assigned per room. A hardcoded name->colour map only works
# for one deployment's rooms; every other room fell through to a single
# default. Hashing the name picks a stable colour from the palette instead, so
# any set of rooms gets distinct, consistent colours with no configuration.
RESOURCE_PALETTE = [
    "#1F7067", "#3B5BA5", "#B5452B", "#6B4C9A", "#2E7D32",
    "#A15C00", "#00796B", "#8E3A59", "#455A64", "#5D4037",
]


def resource_color(resource_name):
    import hashlib

    if not resource_name:
        return RESOURCE_PALETTE[0]
    digest = hashlib.sha1(resource_name.encode("utf-8")).hexdigest()
    return RESOURCE_PALETTE[int(digest, 16) % len(RESOURCE_PALETTE)]


@app.route('/get_bookings')
def get_bookings():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Fetch all bookings from the database
    cursor.execute("SELECT id, event_title, start_date, start_time, end_date, end_time, resource FROM bookings")
    bookings = cursor.fetchall()
    cursor.close()
    conn.close()



    events = []
    for booking in bookings:
        # Ensure start_time and end_time are time objects
        start_time = timedelta_to_time(booking['start_time']) if isinstance(booking['start_time'], timedelta) else booking['start_time']
        end_time = timedelta_to_time(booking['end_time']) if isinstance(booking['end_time'], timedelta) else booking['end_time']

        # Combine date and time
        start = datetime.combine(booking['start_date'], start_time)
        end = datetime.combine(booking['end_date'], end_time)

        # Assign a color based on the resource
        color = resource_color(booking['resource'])

        is_all_day = (start_time == time(0, 0, 0) and end_time == time(23, 59, 59))

        events.append({
            'Id': booking['id'],
            'Subject': booking['event_title'],
            'Description': f"Resource: {booking['resource']}",
            'StartTime': start.isoformat(),
            'EndTime': end.isoformat(),
            'Color': color,
            'IsAllDay': is_all_day
        })

    return jsonify(events)

@app.route('/get_fullcalendar_css')
def get_fullcalendar_css():
    # Fetch FullCalendar CSS from the CDN
    url = "https://cdn.jsdelivr.net/npm/fullcalendar@5.10.1/main.min.css"
    response = requests.get(url)

    # Return the CSS file with the appropriate headers
    return Response(response.content, mimetype='text/css')

@app.route('/get_fullcalendar_js')
def get_fullcalendar_js():
    # Fetch FullCalendar JavaScript from the CDN
    url = "https://cdn.jsdelivr.net/npm/fullcalendar@5.10.1/main.min.js"
    response = requests.get(url)

    # Return the JavaScript file with the appropriate headers
    return Response(response.content, mimetype='application/javascript')

@app.route('/calendar')
def calendar():
    return render_template('calendar.html')

@app.route('/admin_dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        return "Access denied", 403

    # Fetch total bookings, available rooms, upcoming events, and resources
    total_bookings = get_total_bookings()
    available_rooms = get_available_rooms()
    upcoming_events = get_upcoming_events()
    bookings = get_all_bookings()
    resources = get_all_resources()

    # Fetch inventory with resource names
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT inventory.id, inventory.name, inventory.max_quantity, resources.name as resource_name
        FROM inventory
        JOIN resources ON inventory.resource_id = resources.id
    """)
    inventory = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('admin_dashboard.html', 
                           total_bookings=total_bookings, 
                           available_rooms=available_rooms, 
                           upcoming_events=upcoming_events,
                           bookings=bookings,
                           resources=resources,
                           inventory=inventory)  # Pass inventory to the template

def get_total_bookings():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM bookings")
    total = cursor.fetchone()[0]
    conn.close()
    return total

def get_available_rooms():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM resources")
    available = cursor.fetchone()[0]
    conn.close()
    return available

def get_available_rooms():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM resources WHERE id NOT IN (SELECT id FROM bookings WHERE start_date >= NOW())")
    available = cursor.fetchone()[0]
    conn.close()
    return available

def get_upcoming_events():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM bookings WHERE start_date >= NOW()")
    upcoming = cursor.fetchone()[0]
    conn.close()
    return upcoming

def get_all_bookings():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM bookings")
    bookings = cursor.fetchall()
    conn.close()
    return bookings

def get_all_resources():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Modify the query to include the 'cleaning_charge' field
    cursor.execute("""
        SELECT id, name, capacity, cleaning_charge 
        FROM resources
    """)
    resources = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return resources


@app.route('/add_resource', methods=['POST'])
@login_required
@admin_required
def add_resource():
    resource_name = request.form['resource_name']
    capacity = request.form['capacity']

    # Add the resource to the database
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO resources (name, capacity) VALUES (%s, %s)", (resource_name, capacity))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('admin_dashboard'))

# Admin-only. Previously unauthenticated: any anonymous POST could delete any
# booking by id.
@app.route('/cancel_booking/<int:booking_id>', methods=['POST'])
@login_required
@admin_required
def cancel_booking(booking_id):
    # Connect to the database
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch the booking details before deleting
    cursor.execute("SELECT * FROM bookings WHERE id = %s", (booking_id,))
    booking = cursor.fetchone()

    if not booking:
        cursor.close()
        conn.close()
        return "Booking not found", 404

    # Delete the booking
    cursor.execute("DELETE FROM bookings WHERE id = %s", (booking_id,))
    conn.commit()
    cursor.close()
    conn.close()

    # Send cancellation email
    personal_details = {
        "first_name": booking['first_name'],
        "last_name": booking['last_name'],
        "email": booking['email']
    }
    send_cancellation_notification(personal_details, booking)

    # Redirect back to the admin dashboard after cancellation
    return redirect(url_for('admin_dashboard'))

@app.route('/confirm_cancellation/<int:booking_number>', methods=['POST'])
def confirm_cancellation(booking_number):
    cancellation_code = request.form.get('cancellation_code')

    # Fetch the booking and check if the cancellation code matches
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM bookings WHERE booking_number = %s AND cancellation_code = %s", 
                   (booking_number, cancellation_code))
    booking = cursor.fetchone()

    if booking:
        # Cancel the booking if the code matches
        cursor.execute("DELETE FROM bookings WHERE booking_number = %s", (booking_number,))
        conn.commit()
        cursor.close()
        conn.close()

        # Send cancellation confirmation email to the user
        personal_details = {
            "first_name": booking['first_name'],
            "last_name": booking['last_name'],
            "email": booking['email']
        }
        send_cancellation_notification(personal_details, booking)

        # Render the cancellation confirmation page
        return render_template('cancellation_confirmation.html', booking_number=booking_number)
    else:
        # Return to the cancellation code page with an error message
        cursor.close()
        conn.close()
        error_message = "Invalid cancellation code. Please try again."
        return render_template('enter_cancellation_code.html', booking_number=booking_number, error_message=error_message)


class User(UserMixin):
    def __init__(self, id, username, email, password, role):
        self.id = id
        self.username = username
        self.email = email
        self.password = password
        self.role = role

    def get_id(self):
        return self.id

    @staticmethod
    def get(user_id):
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user_data = cursor.fetchone()
        cursor.close()
        conn.close()

        if user_data:
            return User(user_data['id'], user_data['username'], user_data['email'], user_data['password'], user_data['role'])
        return None

@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

        # Insert the new user into the database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, email, password, role) VALUES (%s, %s, %s, 'user')", 
                       (username, email, hashed_password))
        conn.commit()
        cursor.close()
        conn.close()

        # Send an email notification to the new user
        send_new_user_email(username, email, password)

        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        # Fetch the user from the database
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user_data = cursor.fetchone()
        cursor.close()
        conn.close()

        if user_data:
            # Check if the user is active
            if not user_data['is_active']:
                error_message = "This account is deactivated. Please contact support."
                return render_template('login.html', error_message=error_message)

            # Check if the password is correct
            if bcrypt.check_password_hash(user_data['password'], password):
                # If the password is correct, log in the user
                user = User(user_data['id'], user_data['username'], user_data['email'], user_data['password'], user_data['role'])
                login_user(user)
                return redirect(url_for('admin_dashboard') if user.role == 'admin' else url_for('calendar'))
            else:
                # If the password is incorrect, display an error message
                error_message = "Incorrect password. Please try again."
                return render_template('login.html', error_message=error_message)
        else:
            # If the email doesn't exist, display an error message
            error_message = "No account found with that email. Please register."
            return render_template('login.html', error_message=error_message, show_register_link=True)

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/users')
@login_required
def users():
    if current_user.role != 'admin':
        return "Access denied", 403

    # Fetch all users from the database
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, username, email, role, is_active FROM users")
    users_list = cursor.fetchall()

    # Ensure the is_active field is properly interpreted as a boolean
    for user in users_list:
        user['is_active'] = bool(user['is_active'])  # Convert 1 or 0 to True or False

    cursor.close()
    conn.close()

    return render_template('users.html', users=users_list)

@app.route('/promote_user/<int:user_id>', methods=['POST'])
@login_required
def promote_user(user_id):
    if current_user.role != 'admin':
        return "Access denied", 403

    # Promote user to admin
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET role = 'admin' WHERE id = %s", (user_id,))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('users'))

def send_new_user_email(username, email, password):
    email_body = render_template(
        'new_user_email.html',  # Custom HTML email template
        username=username,
        email=email,
        password=password
    )
    
    # Send email to the new user
    send_mail("Your New Account Has Been Created", [email], html=email_body)


@app.route('/add_user', methods=['GET', 'POST'])
@login_required
def add_user():
    if current_user.role != 'admin':
        return "Access denied", 403

    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        role = request.form['role']  # 'user' or 'admin'

        # Hash the password before storing
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

        # Insert new user into the database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, email, password, role) VALUES (%s, %s, %s, %s)", 
                       (username, email, hashed_password, role))
        conn.commit()
        cursor.close()
        conn.close()

        # Send an email notification to the new user
        send_new_user_email(username, email, password)

        return redirect(url_for('users'))

    return render_template('add_user.html')


@app.route('/deactivate_user/<int:user_id>', methods=['POST'])
@login_required
def deactivate_user(user_id):
    if current_user.role != 'admin':
        return "Access denied", 403

    # Deactivate user by setting is_active to False
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_active = %s WHERE id = %s", (False, user_id))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('users'))

@app.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if current_user.role != 'admin':
        return "Access denied", 403

    # Permanently delete the user
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('users'))

@app.route('/activate_user/<int:user_id>', methods=['POST'])
@login_required
def activate_user(user_id):
    if current_user.role != 'admin':
        return "Access denied", 403

    # Activate user by setting is_active to True
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_active = %s WHERE id = %s", (True, user_id))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('users'))

@app.route('/initiate_cancellation/<int:booking_number>', methods=['POST'])
def initiate_cancellation(booking_number):
    # Generate a cancellation code
    cancellation_code = random.randint(100000, 999999)
    
    # Update the database with the cancellation code
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Fetch the booking details to get the email of the contact person
    cursor.execute("SELECT email FROM bookings WHERE booking_number = %s", (booking_number,))
    booking = cursor.fetchone()
    
    if booking:
        email = booking['email']

        # Store the cancellation code in the database
        cursor.execute("UPDATE bookings SET cancellation_code = %s WHERE booking_number = %s", (cancellation_code, booking_number))
        conn.commit()

        # Send the cancellation code to the user's email
        send_cancellation_email(email, cancellation_code)

        cursor.close()
        conn.close()

        # Render the form for the user to enter the cancellation code
        return render_template('enter_cancellation_code.html', booking_number=booking_number)
    
    else:
        cursor.close()
        conn.close()
        return "Booking not found.", 404

def send_cancellation_email(email, cancellation_code):
    """Send the cancellation code.

    This previously opened its own smtplib connection with a SECOND copy of the
    SMTP credentials hardcoded in source, bypassing the configured mail setup.
    It now uses the same path as every other message.
    """
    send_mail(
        subject="Your Booking Cancellation Code",
        recipients=[email],
        body=f"Your cancellation code is: {cancellation_code}",
    )


@app.route('/delete_resource/<int:resource_id>', methods=['POST'])
@login_required
def delete_resource(resource_id):
    if current_user.role != 'admin':
        return "Access denied", 403
    
    # Connect to the database
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if the resource exists
    cursor.execute("SELECT * FROM resources WHERE id = %s", (resource_id,))
    resource = cursor.fetchone()

    if resource:
        # Delete the resource
        cursor.execute("DELETE FROM resources WHERE id = %s", (resource_id,))
        conn.commit()
        cursor.close()
        conn.close()
        
        return redirect(url_for('admin_dashboard'))  # Redirect back to the admin dashboard
    else:
        cursor.close()
        conn.close()
        return "Resource not found", 404


@app.route('/add_inventory', methods=['POST'])
@login_required
def add_inventory():
    if current_user.role != 'admin':
        return "Access denied", 403

    resource_id = request.form['resource_id']
    inventory_name = request.form['inventory_name']
    max_quantity = request.form['max_quantity']

    # Insert new inventory into the database
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO inventory (resource_id, name, max_quantity) VALUES (%s, %s, %s)", 
                   (resource_id, inventory_name, max_quantity))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('admin_dashboard'))

@app.route('/delete_inventory/<int:inventory_id>', methods=['POST'])
@login_required
def delete_inventory(inventory_id):
    if current_user.role != 'admin':
        return "Access denied", 403

    # Delete the inventory item from the database
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM inventory WHERE id = %s", (inventory_id,))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('admin_dashboard'))

@app.route('/edit_resource', methods=['POST'])
@login_required
def edit_resource():
    if current_user.role != 'admin':
        return "Access denied", 403
    
    resource_id = request.form.get('resource_id')
    resource_name = request.form.get('resource_name')
    capacity = request.form.get('capacity')
    cleaning_charge = request.form.get('cleaning_charge')

    # Update resource in the database
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE resources
        SET name = %s, capacity = %s, cleaning_charge = %s
        WHERE id = %s
    """, (resource_name, capacity, cleaning_charge, resource_id))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('admin_dashboard'))

@app.route('/edit_inventory', methods=['POST'])
@login_required
def edit_inventory():
    if current_user.role != 'admin':
        return "Access denied", 403

    inventory_id = request.form.get('inventory_id')
    inventory_name = request.form.get('inventory_name')
    max_quantity = request.form.get('max_quantity')

    # Update inventory in the database
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE inventory
        SET name = %s, max_quantity = %s
        WHERE id = %s
    """, (inventory_name, max_quantity, inventory_id))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('admin_dashboard'))


if __name__ == '__main__':
    app.run(debug=True, port=8080)
