from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your_secret_key_here')

def get_db():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD', 'password'),
        database=os.getenv('DB_NAME', 'ecommerce')
    )

# Decorator to restrict access to logged-in users
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'error')
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# Decorator to restrict access to administrators
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash('Administrator access required.', 'error')
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# ---------- REGISTRATION & LOGIN ----------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '').strip()

        if not username or not email or not phone or not password:
            flash('All fields are required.', 'error')
            return redirect(url_for('register'))

        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute("""
            SELECT id
            FROM users
            WHERE username=%s
               OR email=%s
               OR phone=%s
        """, (username, email, phone))

        existing_user = cursor.fetchone()

        if existing_user:
            cursor.close()
            db.close()
            flash('Username, email or phone already exists.', 'error')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password)

        cursor.execute("""
            INSERT INTO users
            (username, email, phone, password, role)
            VALUES (%s, %s, %s, %s, 'user')
        """, (
            username,
            email,
            phone,
            hashed_password
        ))

        db.commit()

        cursor.close()
        db.close()

        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')
    
@app.route('/login', methods=['GET', 'POST'])
def login():

    if 'user_id' in session:
        return redirect(url_for('index'))

    next_page = request.args.get('next', '')

    if request.method == 'POST':

        login_id = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not login_id or not password:
            flash(
                'Username/Email/Phone and password are required.',
                'error'
            )
            return redirect(url_for('login', next=next_page))

        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute("""
            SELECT *
            FROM users
            WHERE username=%s
               OR email=%s
               OR phone=%s
        """, (
            login_id,
            login_id,
            login_id
        ))

        user = cursor.fetchone()

        cursor.close()
        db.close()

        if user and check_password_hash(
            user['password'],
            password
        ):

            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']

            flash(
                f"Welcome back, {user['username']}!",
                'success'
            )

            if next_page:
                return redirect(next_page)

            return redirect(url_for('index'))

        flash('Invalid credentials.', 'error')
        return redirect(url_for('login', next=next_page))

    return render_template('login.html')
    
@app.route('/logout')
def logout():
    session.clear()
    flash('You have logged out successfully.', 'success')
    return redirect(url_for('index'))

# ---------- HOME WITH SEARCH, FILTER & SORTING ----------
@app.route('/')
def index():
    search_query = request.args.get('search', '').strip()
    min_price = request.args.get('min_price', '').strip()
    max_price = request.args.get('max_price', '').strip()
    sort_by = request.args.get('sort', '').strip()
    category = request.args.get('category', '').strip()

    query = "SELECT * FROM products"
    where_clauses = []
    query_params = []

    if search_query:
        where_clauses.append("(name LIKE %s OR description LIKE %s)")
        search_param = f"%{search_query}%"
        query_params.extend([search_param, search_param])

    if min_price:
        try:
            where_clauses.append("price >= %s")
            query_params.append(float(min_price))
        except ValueError:
            pass

    if max_price:
        try:
            where_clauses.append("price <= %s")
            query_params.append(float(max_price))
        except ValueError:
            pass
    
    if category:
        where_clauses.append("category = %s")
        query_params.append(category)
    
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)

    sort_options = {
        "price_asc": "ORDER BY price ASC",
        "price_desc": "ORDER BY price DESC",
        "name_asc": "ORDER BY name ASC",
        "name_desc": "ORDER BY name DESC"
    }
    if sort_by in sort_options:
        query += " " + sort_options[sort_by]
    else:
        query += " ORDER BY id DESC"

    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute(query, tuple(query_params))
    products = cursor.fetchall()
    cursor.execute("""
        SELECT name AS category
        FROM categories
        ORDER BY name
    """)

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

# ---------- PRODUCT DETAIL ----------
@app.route('/product/<int:product_id>')
def product(product_id):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
    product = cursor.fetchone()
    cursor.close()
    db.close()
    if not product:
        return redirect(url_for('index'))
    return render_template('product.html', product=product)

# ---------- CART ----------
@app.route('/cart')
def cart():
    products = []
    total = 0
    
    if 'user_id' in session:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("""
            SELECT p.*, c.quantity, (p.price * c.quantity) as subtotal
            FROM cart_items c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = %s
        """, (session['user_id'],))
        products = cursor.fetchall()
        total = sum(p['subtotal'] for p in products)
        cursor.close()
        db.close()
    else:
        cart_items = session.get('cart', {})
        db = get_db()
        cursor = db.cursor(dictionary=True)
        for pid, qty in cart_items.items():
            cursor.execute("SELECT * FROM products WHERE id = %s", (int(pid),)) # Fixed string to int conversion
            p = cursor.fetchone()
            if p:
                p['quantity'] = qty
                p['subtotal'] = p['price'] * qty
                total += p['subtotal']
                products.append(p)
        cursor.close()
        db.close()
        
    return render_template('cart.html', products=products, total=total)

@app.route('/cart/add/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    if 'user_id' in session:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO cart_items (user_id, product_id, quantity)
            VALUES (%s, %s, 1)
            ON DUPLICATE KEY UPDATE quantity = quantity + 1
        """, (session['user_id'], product_id))
        db.commit()
        cursor.close()
        db.close()
    else:
        cart = session.get('cart', {})
        key = str(product_id)
        cart[key] = cart.get(key, 0) + 1
        session['cart'] = cart
        
    flash('Item added to cart.', 'success')
    return redirect(url_for('cart'))

@app.route('/cart/remove/<int:product_id>')
def remove_from_cart(product_id):
    if 'user_id' in session:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("DELETE FROM cart_items WHERE user_id = %s AND product_id = %s", (session['user_id'], product_id))
        db.commit()
        cursor.close()
        db.close()
    else:
        cart = session.get('cart', {})
        cart.pop(str(product_id), None)
        session['cart'] = cart
        
    flash('Item removed from cart.', 'success')
    return redirect(url_for('cart'))

# ---------- CHECKOUT ----------
@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    user_id = session['user_id']
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip()
        city = request.form.get('city', '').strip()
        pin = request.form.get('pin', '').strip()

        cursor.execute("""
            UPDATE users
            SET email = %s,
                phone = %s,
                address = %s,
                city = %s,
                pin = %s
            WHERE id = %s
        """, (
            email,
            phone,
            address,
            city,
            pin,
            user_id
        ))

        db.commit()
        
        cursor.execute("DELETE FROM cart_items WHERE user_id = %s", (user_id,))
        db.commit()
        
        cursor.close()
        db.close()
        return redirect(url_for('order_success')) # Post/Redirect/Get Pattern optimization
        
    # --- GET REQUEST HANDLING ---
    cursor.execute("""
        SELECT SUM(p.price * c.quantity) as total
        FROM cart_items c
        JOIN products p ON c.product_id = p.id
        WHERE c.user_id = %s
    """, (user_id,))
    result = cursor.fetchone()
    total = result['total'] if result and result['total'] else 0
    
    if total == 0:
        cursor.close()
        db.close()
        flash('Your cart is empty.', 'error')
        return redirect(url_for('cart'))
        
    cursor.execute("""
    SELECT
        username,
        email,
        phone,
        address,
        city,
        pin
    FROM users
    WHERE id = %s
""", (user_id,))
    user_profile = cursor.fetchone()
    
    cursor.close()
    db.close()
    
    return render_template('checkout.html', total=total, user_profile=user_profile)
@app.route('/cart/increase/<int:product_id>')
@login_required
def increase_cart(product_id):

    if 'user_id' in session:
        db = get_db()
        cursor = db.cursor()

        cursor.execute("""
            UPDATE cart_items
            SET quantity = quantity + 1
            WHERE user_id = %s
              AND product_id = %s
        """, (session['user_id'], product_id))

        db.commit()
        cursor.close()
        db.close()

    return redirect(url_for('cart'))
@app.route('/cart/decrease/<int:product_id>')
@login_required
def decrease_cart(product_id):

    if 'user_id' in session:

        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute("""
            SELECT quantity
            FROM cart_items
            WHERE user_id = %s
              AND product_id = %s
        """, (session['user_id'], product_id))

        item = cursor.fetchone()

        if item:

            if item['quantity'] > 1:

                cursor.execute("""
                    UPDATE cart_items
                    SET quantity = quantity - 1
                    WHERE user_id = %s
                      AND product_id = %s
                """, (session['user_id'], product_id))

            else:

                cursor.execute("""
                    DELETE FROM cart_items
                    WHERE user_id = %s
                      AND product_id = %s
                """, (session['user_id'], product_id))

        db.commit()
        cursor.close()
        db.close()

    return redirect(url_for('cart'))
@app.route('/order_success')
@login_required
def order_success():
    return render_template('order_success.html')

# ---------- ADMIN ----------
@app.route('/admin')
@admin_required
def admin():

    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM products")
    products = cursor.fetchall()

    cursor.execute("""
        SELECT *
        FROM categories
        ORDER BY name
    """)
    categories = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
        'admin.html',
        products=products,
        categories=categories
    )
@app.route('/admin/add', methods=['POST'])
@admin_required
def admin_add():

    name = request.form['name']
    category = request.form['category']
    price = request.form['price']
    description = request.form['description']
    image_url = request.form['image_url']

    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        INSERT INTO products
        (name, category, price, description, image_url)
        VALUES (%s, %s, %s, %s, %s)
    """, (
        name,
        category,
        price,
        description,
        image_url
    ))

    db.commit()

    cursor.close()
    db.close()

    flash('Product added successfully.', 'success')
    return redirect(url_for('admin'))
@app.route('/admin/add-category', methods=['POST'])
@admin_required
def add_category():

    category_name = request.form['category_name'].strip()

    if not category_name:
        flash('Category name is required.', 'error')
        return redirect(url_for('admin'))

    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        INSERT IGNORE INTO categories(name)
        VALUES(%s)
    """, (category_name,))

    db.commit()

    cursor.close()
    db.close()

    flash('Category added successfully.', 'success')

    return redirect(url_for('admin'))
@app.route('/admin/delete/<int:product_id>')
@admin_required
def admin_delete(product_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM products WHERE id = %s", (product_id,))
    db.commit()
    cursor.close()
    db.close()
    flash('Product deleted successfully.', 'success')
    return redirect(url_for('admin'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
