# ShopEase — Flask E-Commerce App

## Project Structure
```
ecommerce/
├── app.py              # Main Flask application
├── schema.sql          # MySQL database setup
├── requirements.txt    # Python dependencies
├── Dockerfile          # Container config
└── templates/          # HTML pages
    ├── base.html
    ├── index.html       # Home / product listing
    ├── product.html     # Product detail
    ├── cart.html        # Shopping cart
    ├── checkout.html    # Checkout form
    ├── order_success.html
    └── admin.html       # Admin panel
```

## Local Setup

### 1. Set up MySQL
```bash
mysql -u root -p < schema.sql
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Run the app
```bash
export DB_HOST=localhost
export DB_USER=root
export DB_PASSWORD=yourpassword
export DB_NAME=ecommerce
python app.py
```
Open: http://localhost:5000

## Docker Setup
```bash
docker build -t shopease .
docker run -p 5000:5000 \
  -e DB_HOST=host.docker.internal \
  -e DB_USER=root \
  -e DB_PASSWORD=yourpassword \
  -e DB_NAME=ecommerce \
  shopease
```

## Environment Variables
| Variable     | Default    | Description          |
|--------------|------------|----------------------|
| DB_HOST      | localhost  | MySQL host           |
| DB_USER      | root       | MySQL username       |
| DB_PASSWORD  | password   | MySQL password       |
| DB_NAME      | ecommerce  | Database name        |

## Pages
- `/`         → Product listing
- `/product/<id>` → Product detail
- `/cart`     → Shopping cart
- `/checkout` → Checkout
- `/admin`    → Admin panel (add/delete products)
