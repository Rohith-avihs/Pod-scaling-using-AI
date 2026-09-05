import firebase_admin
from firebase_admin import credentials, firestore
import mysql.connector
from werkzeug.security import generate_password_hash

# -----------------------------
# Firebase
# -----------------------------
cred = credentials.Certificate("firebase-key.json")

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

fs = firestore.client()

# -----------------------------
# MySQL
# -----------------------------
mysql_db = mysql.connector.connect(
    host="127.0.0.1",
    port=3306,
    user="shopease",
    password="yourpassword",
    database="ecommerce"
)

cursor = mysql_db.cursor()

# -----------------------------
# Read Firestore data
# -----------------------------
users = list(fs.collection("users").stream())
products = list(fs.collection("products").stream())
categories = list(fs.collection("categories").stream())

print("Firestore data:")
print("Users:", len(users))
print("Products:", len(products))
print("Categories:", len(categories))

# -----------------------------
# Migrate Categories
# -----------------------------
print("\nMigrating categories...")

for doc in categories:
    data = doc.to_dict()
    name = data.get("name")

    if not name:
        continue

    cursor.execute(
        "SELECT id FROM categories WHERE name = %s",
        (name,)
    )

    if cursor.fetchone() is None:
        cursor.execute(
            "INSERT INTO categories (name) VALUES (%s)",
            (name,)
        )

print("Categories migration complete.")

# -----------------------------
# Migrate Products
# -----------------------------
print("\nMigrating products...")

for doc in products:
    data = doc.to_dict()

    name = data.get("name")
    price = data.get("price", 0)
    description = data.get("description", "")
    image_url = data.get("image_url", "")
    category = data.get("category", "Accessories")

    if not name:
        continue

    cursor.execute(
        "SELECT id FROM products WHERE name = %s",
        (name,)
    )

    if cursor.fetchone() is None:
        cursor.execute(
            """
            INSERT INTO products
            (name, price, description, image_url, category)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                name,
                price,
                description,
                image_url,
                category
            )
        )

print("Products migration complete.")

# -----------------------------
# Migrate Users
# -----------------------------
print("\nMigrating users...")

for doc in users:
    data = doc.to_dict()

    username = data.get("username")
    email = data.get("email")
    phone = data.get("phone")
    password = data.get("password")
    role = data.get("role", "user")
    address = data.get("address", "")
    city = data.get("city", "")
    pin = data.get("pin", "")

    if not username:
        continue

    cursor.execute(
        "SELECT id FROM users WHERE username = %s",
        (username,)
    )

    if cursor.fetchone() is not None:
        continue

    cursor.execute(
        """
        INSERT INTO users
        (username, email, phone, password, role, address, city, pin)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            username,
            email,
            phone,
            password,
            role,
            address,
            city,
            pin
        )
    )

print("Users migration complete.")

# -----------------------------
# Commit
# -----------------------------
mysql_db.commit()

# -----------------------------
# Verify
# -----------------------------
print("\nMigration completed successfully!")

for table in ["users", "products", "categories", "cart_items"]:
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    count = cursor.fetchone()[0]
    print(f"{table}: {count}")

cursor.close()
mysql_db.close()
