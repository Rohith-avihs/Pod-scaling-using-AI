from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import firebase_admin
from firebase_admin import credentials, firestore
import os

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'shopease_secret_key')
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')

# ── Firebase Init ──────────────────────────────────────────────────────────────
if not firebase_admin._apps:
    cred = credentials.Certificate(os.getenv('FIREBASE_KEY', 'firebase-key.json'))
    firebase_admin.initialize_app(cred, {'projectId': 'shopease-24'})
db = firestore.client()

# ── Auth Decorators ────────────────────────────────────────────────────────────
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

# ── Auth Routes ────────────────────────────────────────────────────────────────
@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email    = request.form.get('email', '').strip()
        phone    = request.form.get('phone', '').strip()
        password = request.form.get('password', '').strip()

        if not all([username, email, phone, password]):
            flash('All fields are required.', 'error')
            return redirect(url_for('register'))

        # check existing
        existing = db.collection('users').where('username', '==', username).limit(1).get()
        if existing:
            flash('Username already exists.', 'error')
            return redirect(url_for('register'))

        existing_email = db.collection('users').where('email', '==', email).limit(1).get()
        if existing_email:
            flash('Email already exists.', 'error')
            return redirect(url_for('register'))

        db.collection('users').add({
            'username': username,
            'email': email,
            'phone': phone,
            'password': generate_password_hash(password),
            'role': 'user',
            'address': '', 'city': '', 'pin': ''
        })
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

        users = db.collection('users').where('username', '==', login_id).limit(1).get()
        if not users:
            users = db.collection('users').where('email', '==', login_id).limit(1).get()
        if not users:
            users = db.collection('users').where('phone', '==', login_id).limit(1).get()

        if users:
            user_doc = users[0]
            user = user_doc.to_dict()
            if check_password_hash(user['password'], password):
                session['user_id'] = user_doc.id
                session['username'] = user['username']
                session['role'] = user.get('role', 'user')
                flash(f"Welcome back, {user['username']}!", 'success')
                return redirect(next_page or url_for('index'))

        flash('Invalid credentials.', 'error')
        return redirect(url_for('login', next=next_page))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('index'))

# ── Home ───────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    search_query = request.args.get('search', '').strip()
    category     = request.args.get('category', '').strip()
    min_price    = request.args.get('min_price', '').strip()
    max_price    = request.args.get('max_price', '').strip()
    sort_by      = request.args.get('sort', '').strip()

    products_ref = db.collection('products')
    if category:
        products_ref = products_ref.where('category', '==', category)
    docs = products_ref.get()

    products = []
    for doc in docs:
        p = doc.to_dict()
        p['id'] = doc.id
        if search_query and search_query.lower() not in p['name'].lower():
            continue
        if min_price:
            try:
                if p['price'] < float(min_price): continue
            except: pass
        if max_price:
            try:
                if p['price'] > float(max_price): continue
            except: pass
        products.append(p)

    if sort_by == 'price_asc':
        products.sort(key=lambda x: x['price'])
    elif sort_by == 'price_desc':
        products.sort(key=lambda x: x['price'], reverse=True)
    elif sort_by == 'name_asc':
        products.sort(key=lambda x: x['name'])

    categories = [doc.to_dict() for doc in db.collection('categories').get()]
    return render_template('index.html', products=products, categories=categories,
                           search_query=search_query, min_price=min_price,
                           max_price=max_price, sort_by=sort_by, category=category)

# ── Product Detail ─────────────────────────────────────────────────────────────
@app.route('/product/<product_id>')
def product(product_id):
    doc = db.collection('products').document(product_id).get()
    if not doc.exists:
        return redirect(url_for('index'))
    p = doc.to_dict()
    p['id'] = doc.id
    return render_template('product.html', product=p)

# ── Cart ───────────────────────────────────────────────────────────────────────
@app.route('/cart')
def cart():
    products, total = [], 0
    if 'user_id' in session:
        cart_docs = db.collection('users').document(session['user_id'])\
                      .collection('cart').get()
        for item in cart_docs:
            c = item.to_dict()
            p_doc = db.collection('products').document(c['product_id']).get()
            if p_doc.exists:
                p = p_doc.to_dict()
                p['id'] = p_doc.id
                p['quantity'] = c['quantity']
                p['subtotal'] = p['price'] * c['quantity']
                total += p['subtotal']
                products.append(p)
    else:
        cart_items = session.get('cart', {})
        for pid, qty in cart_items.items():
            p_doc = db.collection('products').document(pid).get()
            if p_doc.exists:
                p = p_doc.to_dict()
                p['id'] = p_doc.id
                p['quantity'] = qty
                p['subtotal'] = p['price'] * qty
                total += p['subtotal']
                products.append(p)
    return render_template('cart.html', products=products, total=total)

@app.route('/cart/add/<product_id>', methods=['POST'])
def add_to_cart(product_id):
    if 'user_id' in session:
        cart_ref = db.collection('users').document(session['user_id'])\
                     .collection('cart').document(product_id)
        doc = cart_ref.get()
        if doc.exists:
            cart_ref.update({'quantity': doc.to_dict()['quantity'] + 1})
        else:
            cart_ref.set({'product_id': product_id, 'quantity': 1})
    else:
        cart = session.get('cart', {})
        cart[product_id] = cart.get(product_id, 0) + 1
        session['cart'] = cart
    flash('Item added to cart.', 'success')
    return redirect(url_for('cart'))

@app.route('/cart/remove/<product_id>')
def remove_from_cart(product_id):
    if 'user_id' in session:
        db.collection('users').document(session['user_id'])\
          .collection('cart').document(product_id).delete()
    else:
        cart = session.get('cart', {})
        cart.pop(product_id, None)
        session['cart'] = cart
    flash('Item removed.', 'success')
    return redirect(url_for('cart'))

@app.route('/cart/increase/<product_id>')
@login_required
def increase_cart(product_id):
    cart_ref = db.collection('users').document(session['user_id'])\
                 .collection('cart').document(product_id)
    doc = cart_ref.get()
    if doc.exists:
        cart_ref.update({'quantity': doc.to_dict()['quantity'] + 1})
    return redirect(url_for('cart'))

@app.route('/cart/decrease/<product_id>')
@login_required
def decrease_cart(product_id):
    cart_ref = db.collection('users').document(session['user_id'])\
                 .collection('cart').document(product_id)
    doc = cart_ref.get()
    if doc.exists:
        qty = doc.to_dict()['quantity']
        if qty > 1:
            cart_ref.update({'quantity': qty - 1})
        else:
            cart_ref.delete()
    return redirect(url_for('cart'))

# ── Checkout ───────────────────────────────────────────────────────────────────
@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    user_id = session['user_id']
    if request.method == 'POST':
        db.collection('users').document(user_id).update({
            'email':   request.form.get('email', ''),
            'phone':   request.form.get('phone', ''),
            'address': request.form.get('address', ''),
            'city':    request.form.get('city', ''),
            'pin':     request.form.get('pin', ''),
        })
        cart_docs = db.collection('users').document(user_id).collection('cart').get()
        for doc in cart_docs:
            doc.reference.delete()
        return redirect(url_for('order_success'))

    cart_docs = db.collection('users').document(user_id).collection('cart').get()
    total = 0
    for item in cart_docs:
        c = item.to_dict()
        p_doc = db.collection('products').document(c['product_id']).get()
        if p_doc.exists:
            total += p_doc.to_dict()['price'] * c['quantity']

    if total == 0:
        flash('Your cart is empty.', 'error')
        return redirect(url_for('cart'))

    user_doc = db.collection('users').document(user_id).get()
    user_profile = user_doc.to_dict() if user_doc.exists else {}
    return render_template('checkout.html', total=total, user_profile=user_profile)

@app.route('/order_success')
@login_required
def order_success():
    return render_template('order_success.html')

# ── Admin ──────────────────────────────────────────────────────────────────────
@app.route('/admin')
@admin_required
def admin():
    products = [dict(doc.to_dict(), id=doc.id)
                for doc in db.collection('products').get()]
    categories = [doc.to_dict() for doc in db.collection('categories').get()]
    return render_template('admin.html', products=products, categories=categories)

@app.route('/admin/add', methods=['POST'])
@admin_required
def admin_add():
    db.collection('products').add({
        'name':        request.form['name'],
        'category':    request.form['category'],
        'price':       float(request.form['price']),
        'description': request.form['description'],
        'image_url':   request.form['image_url'],
    })
    flash('Product added successfully.', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/add-category', methods=['POST'])
@admin_required
def add_category():
    name = request.form['category_name'].strip()
    if name:
        existing = db.collection('categories').where('name', '==', name).limit(1).get()
        if not existing:
            db.collection('categories').add({'name': name})
            flash('Category added.', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/delete/<product_id>')
@admin_required
def admin_delete(product_id):
    db.collection('products').document(product_id).delete()
    flash('Product deleted.', 'success')
    return redirect(url_for('admin'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
