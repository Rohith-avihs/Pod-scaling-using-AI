
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from prometheus_flask_exporter import PrometheusMetrics
import mysql.connector
import os

app = Flask(__name__)

# Prometheus metrics
metrics = PrometheusMetrics(app)

# Flask configuration
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'shopease_secret_key')

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax'
)


# ─────────────────────────────────────────────────────────────────────────────
# MySQL Database
# ─────────────────────────────────────────────────────────────────────────────

def get_db():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST', 'mysql-service'),
        user=os.getenv('DB_USER', 'shopease'),
        password=os.getenv('DB_PASSWORD', 'yourpassword'),
        database=os.getenv('DB_NAME', 'ecommerce')
    )


# ─────────────────────────────────────────────────────────────────────────────
# Auth Decorators
# ─────────────────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'error')
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)

    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash('Administrator access required.', 'error')
            return redirect(url_for('login'))

        return f(*args, **kwargs)

    return decorated


# ─────────────────────────────────────────────────────────────────────────────
# Registration
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/register', methods=['GET', 'POST'])
def register():

    if 'user_id' in session:
        return redirect(url_for('index'))

    if request.method == 'POST':

        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '').strip()

        if not all([username, email, phone, password]):
            flash('All fields are required.', 'error')
            return redirect(url_for('register'))

        db = get_db()
        cursor = db.cursor(dictionary=True)

        # Check username
        cursor.execute(
            "SELECT id FROM users WHERE username = %s LIMIT 1",
            (username,)
        )

        if cursor.fetchone():
            cursor.close()
            db.close()

            flash('Username already exists.', 'error')
            return redirect(url_for('register'))

        # Check email
        cursor.execute(
            "SELECT id FROM users WHERE email = %s LIMIT 1",
            (email,)
        )

        if cursor.fetchone():
            cursor.close()
            db.close()

            flash('Email already exists.', 'error')
            return redirect(url_for('register'))

        # Check phone
        cursor.execute(
            "SELECT id FROM users WHERE phone = %s LIMIT 1",
            (phone,)
        )

        if cursor.fetchone():
            cursor.close()
            db.close()

            flash('Phone number already exists.', 'error')
            return redirect(url_for('register'))

        # Create user
        hashed_password = generate_password_hash(password)

        cursor.execute(
            """
            INSERT INTO users
            (username, email, phone, password, role, address, city, pin)
            VALUES (%s, %s, %s, %s, 'user', '', '', '')
            """,
            (
                username,
                email,
                phone,
                hashed_password
            )
        )

        db.commit()

        cursor.close()
        db.close()

        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


# ─────────────────────────────────────────────────────────────────────────────
# Login
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():

    if 'user_id' in session:
        return redirect(url_for('index'))

    next_page = request.args.get('next', '')

    if request.method == 'POST':

        login_id = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        db = get_db()
        cursor = db.cursor(dictionary=True)

        # Username
        cursor.execute(
            """
            SELECT *
            FROM users
            WHERE username = %s
            LIMIT 1
            """,
            (login_id,)
        )

        user = cursor.fetchone()

        # Email
        if not user:
            cursor.execute(
                """
                SELECT *
                FROM users
                WHERE email = %s
                LIMIT 1
                """,
                (login_id,)
            )

            user = cursor.fetchone()

        # Phone
        if not user:
            cursor.execute(
                """
                SELECT *
                FROM users
                WHERE phone = %s
                LIMIT 1
                """,
                (login_id,)
            )

            user = cursor.fetchone()

        cursor.close()
        db.close()

        if user:

            if check_password_hash(user['password'], password):

                session['user_id'] = user['id']
                session['username'] = user['username']
                session['role'] = user.get('role', 'user')

                flash(
                    f"Welcome back, {user['username']}!",
                    'success'
                )

                return redirect(
                    next_page or url_for('index')
                )

        flash('Invalid credentials.', 'error')

        return redirect(
            url_for('login', next=next_page)
        )

    return render_template('login.html')


# ─────────────────────────────────────────────────────────────────────────────
# Logout
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/logout')
def logout():

    session.clear()

    flash('Logged out successfully.', 'success')

    return redirect(url_for('index'))


# ─────────────────────────────────────────────────────────────────────────────
# Home
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/')
def index():

    search_query = request.args.get('search', '').strip()
    category = request.args.get('category', '').strip()
    min_price = request.args.get('min_price', '').strip()
    max_price = request.args.get('max_price', '').strip()
    sort_by = request.args.get('sort', '').strip()

    db = get_db()
    cursor = db.cursor(dictionary=True)

    # Get products
    if category:

        cursor.execute(
            """
            SELECT *
            FROM products
            WHERE category = %s
            """,
            (category,)
        )

    else:

        cursor.execute(
            """
            SELECT *
            FROM products
            """
        )

    products = cursor.fetchall()

    cursor.close()
    db.close()

    # Apply search and price filtering
    filtered_products = []

    for p in products:

        if search_query:

            if search_query.lower() not in p['name'].lower():
                continue

        if min_price:

            try:

                if float(p['price']) < float(min_price):
                    continue

            except (ValueError, TypeError):
                pass

        if max_price:

            try:

                if float(p['price']) > float(max_price):
                    continue

            except (ValueError, TypeError):
                pass

        filtered_products.append(p)

    products = filtered_products

    # Sorting
    if sort_by == 'price_asc':

        products.sort(
            key=lambda x: float(x['price'])
        )

    elif sort_by == 'price_desc':

        products.sort(
            key=lambda x: float(x['price']),
            reverse=True
        )

    elif sort_by == 'name_asc':

        products.sort(
            key=lambda x: x['name'].lower()
        )

    # Categories
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT *
        FROM categories
        ORDER BY name
        """
    )

    categories = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
        'index.html',
        products=products,
        categories=categories,
        search_query=search_query,
        min_price=min_price,
        max_price=max_price,
        sort_by=sort_by,
        category=category
    )


# ─────────────────────────────────────────────────────────────────────────────
# Product Detail
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/product/<product_id>')
def product(product_id):

    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT *
        FROM products
        WHERE id = %s
        LIMIT 1
        """,
        (product_id,)
    )

    p = cursor.fetchone()

    cursor.close()
    db.close()

    if not p:
        return redirect(url_for('index'))

    return render_template(
        'product.html',
        product=p
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cart
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/cart')
def cart():

    products = []
    total = 0

    if 'user_id' in session:

        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                p.id,
                p.name,
                p.price,
                p.description,
                p.image_url,
                p.category,
                c.quantity,
                (p.price * c.quantity) AS subtotal
            FROM cart_items c
            JOIN products p
                ON c.product_id = p.id
            WHERE c.user_id = %s
            """,
            (session['user_id'],)
        )

        products = cursor.fetchall()

        cursor.close()
        db.close()

        for p in products:

            total += float(p['subtotal'])

    else:

        cart_items = session.get('cart', {})

        if cart_items:

            db = get_db()
            cursor = db.cursor(dictionary=True)

            for pid, qty in cart_items.items():

                cursor.execute(
                    """
                    SELECT *
                    FROM products
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (pid,)
                )

                p = cursor.fetchone()

                if p:

                    p['quantity'] = qty
                    p['subtotal'] = float(p['price']) * qty

                    total += p['subtotal']

                    products.append(p)

            cursor.close()
            db.close()

    return render_template(
        'cart.html',
        products=products,
        total=total
    )


# ─────────────────────────────────────────────────────────────────────────────
# Add to Cart
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/cart/add/<product_id>', methods=['POST'])
def add_to_cart(product_id):

    if 'user_id' in session:

        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT quantity
            FROM cart_items
            WHERE user_id = %s
              AND product_id = %s
            LIMIT 1
            """,
            (
                session['user_id'],
                product_id
            )
        )

        existing = cursor.fetchone()

        if existing:

            cursor.execute(
                """
                UPDATE cart_items
                SET quantity = quantity + 1
                WHERE user_id = %s
                  AND product_id = %s
                """,
                (
                    session['user_id'],
                    product_id
                )
            )

        else:

            cursor.execute(
                """
                INSERT INTO cart_items
                (user_id, product_id, quantity)
                VALUES (%s, %s, 1)
                """,
                (
                    session['user_id'],
                    product_id
                )
            )

        db.commit()

        cursor.close()
        db.close()

    else:

        cart_items = session.get('cart', {})

        product_id = str(product_id)

        cart_items[product_id] = (
            cart_items.get(product_id, 0) + 1
        )

        session['cart'] = cart_items

    flash('Item added to cart.', 'success')

    return redirect(url_for('cart'))


# ─────────────────────────────────────────────────────────────────────────────
# Remove From Cart
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/cart/remove/<product_id>')
def remove_from_cart(product_id):

    if 'user_id' in session:

        db = get_db()
        cursor = db.cursor()

        cursor.execute(
            """
            DELETE FROM cart_items
            WHERE user_id = %s
              AND product_id = %s
            """,
            (
                session['user_id'],
                product_id
            )
        )

        db.commit()

        cursor.close()
        db.close()

    else:

        cart_items = session.get('cart', {})

        cart_items.pop(
            str(product_id),
            None
        )

        session['cart'] = cart_items

    flash('Item removed.', 'success')

    return redirect(url_for('cart'))


# ─────────────────────────────────────────────────────────────────────────────
# Increase Cart Quantity
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/cart/increase/<product_id>')
@login_required
def increase_cart(product_id):

    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        """
        UPDATE cart_items
        SET quantity = quantity + 1
        WHERE user_id = %s
          AND product_id = %s
        """,
        (
            session['user_id'],
            product_id
        )
    )

    db.commit()

    cursor.close()
    db.close()

    return redirect(url_for('cart'))


# ─────────────────────────────────────────────────────────────────────────────
# Decrease Cart Quantity
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/cart/decrease/<product_id>')
@login_required
def decrease_cart(product_id):

    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT quantity
        FROM cart_items
        WHERE user_id = %s
          AND product_id = %s
        LIMIT 1
        """,
        (
            session['user_id'],
            product_id
        )
    )

    item = cursor.fetchone()

    if item:

        if item['quantity'] > 1:

            cursor.execute(
                """
                UPDATE cart_items
                SET quantity = quantity - 1
                WHERE user_id = %s
                  AND product_id = %s
                """,
                (
                    session['user_id'],
                    product_id
                )
            )

        else:

            cursor.execute(
                """
                DELETE FROM cart_items
                WHERE user_id = %s
                  AND product_id = %s
                """,
                (
                    session['user_id'],
                    product_id
                )
            )

        db.commit()

    cursor.close()
    db.close()

    return redirect(url_for('cart'))


# ─────────────────────────────────────────────────────────────────────────────
# Checkout
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():

    user_id = session['user_id']

    db = get_db()
    cursor = db.cursor(dictionary=True)

    if request.method == 'POST':

        email = request.form.get('email', '')
        phone = request.form.get('phone', '')
        address = request.form.get('address', '')
        city = request.form.get('city', '')
        pin = request.form.get('pin', '')

        # Update user information
        cursor.execute(
            """
            UPDATE users
            SET email = %s,
                phone = %s,
                address = %s,
                city = %s,
                pin = %s
            WHERE id = %s
            """,
            (
                email,
                phone,
                address,
                city,
                pin,
                user_id
            )
        )

        # Clear cart
        cursor.execute(
            """
            DELETE FROM cart_items
            WHERE user_id = %s
            """,
            (user_id,)
        )

        db.commit()

        cursor.close()
        db.close()

        return redirect(
            url_for('order_success')
        )

    # Calculate cart total
    cursor.execute(
        """
        SELECT
            p.price,
            c.quantity
        FROM cart_items c
        JOIN products p
            ON c.product_id = p.id
        WHERE c.user_id = %s
        """,
        (user_id,)
    )

    cart_items = cursor.fetchall()

    total = 0

    for item in cart_items:

        total += (
            float(item['price']) *
            item['quantity']
        )

    if total == 0:

        cursor.close()
        db.close()

        flash(
            'Your cart is empty.',
            'error'
        )

        return redirect(url_for('cart'))

    # User profile
    cursor.execute(
        """
        SELECT *
        FROM users
        WHERE id = %s
        LIMIT 1
        """,
        (user_id,)
    )

    user_profile = cursor.fetchone()

    cursor.close()
    db.close()

    return render_template(
        'checkout.html',
        total=total,
        user_profile=user_profile or {}
    )


# ─────────────────────────────────────────────────────────────────────────────
# Order Success
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/order_success')
@login_required
def order_success():

    return render_template(
        'order_success.html'
    )


# ─────────────────────────────────────────────────────────────────────────────
# Admin
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/admin')
@admin_required
def admin():

    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT *
        FROM products
        ORDER BY id
        """
    )

    products = cursor.fetchall()

    cursor.execute(
        """
        SELECT *
        FROM categories
        ORDER BY name
        """
    )

    categories = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
        'admin.html',
        products=products,
        categories=categories
    )


# ─────────────────────────────────────────────────────────────────────────────
# Admin Add Product
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/admin/add', methods=['POST'])
@admin_required
def admin_add():

    name = request.form['name']
    category = request.form['category']
    price = float(request.form['price'])
    description = request.form['description']
    image_url = request.form['image_url']

    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        """
        INSERT INTO products
        (name, category, price, description, image_url)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            name,
            category,
            price,
            description,
            image_url
        )
    )

    db.commit()

    cursor.close()
    db.close()

    flash(
        'Product added successfully.',
        'success'
    )

    return redirect(url_for('admin'))


# ─────────────────────────────────────────────────────────────────────────────
# Admin Add Category
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/admin/add-category', methods=['POST'])
@admin_required
def add_category():

    name = request.form['category_name'].strip()

    if name:

        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT id
            FROM categories
            WHERE name = %s
            LIMIT 1
            """,
            (name,)
        )

        existing = cursor.fetchone()

        if not existing:

            cursor.execute(
                """
                INSERT INTO categories (name)
                VALUES (%s)
                """,
                (name,)
            )

            db.commit()

            flash(
                'Category added.',
                'success'
            )

        cursor.close()
        db.close()

    return redirect(url_for('admin'))


# ─────────────────────────────────────────────────────────────────────────────
# Admin Delete Product
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/admin/delete/<product_id>')
@admin_required
def admin_delete(product_id):

    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        """
        DELETE FROM products
        WHERE id = %s
        """,
        (product_id,)
    )

    db.commit()

    cursor.close()
    db.close()

    flash(
        'Product deleted.',
        'success'
    )

    return redirect(url_for('admin'))


# ─────────────────────────────────────────────────────────────────────────────
# Application Start
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True
    )
