-- Create tables
CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    description TEXT,
    image_url VARCHAR(500),
    category VARCHAR(100) DEFAULT 'Accessories',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'user',
    email VARCHAR(255) UNIQUE,
    phone VARCHAR(20) UNIQUE,
    address TEXT,
    city VARCHAR(100),
    pin VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cart_items (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, product_id)
);

-- Sample data
INSERT INTO categories (name) VALUES
('Electronics'), ('Footwear'), ('Bags'), ('Accessories')
ON CONFLICT DO NOTHING;

INSERT INTO products (name, price, description, image_url, category) VALUES
('Wireless Headphones', 2999.00, 'Premium sound quality with 30hr battery life', 'https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=400', 'Electronics'),
('Running Shoes', 3499.00, 'Lightweight and breathable for daily runs', 'https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=400', 'Footwear'),
('Smart Watch', 8999.00, 'Fitness tracker with heart rate monitor', 'https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=400', 'Electronics'),
('Laptop Backpack', 1799.00, 'Water-resistant with USB charging port', 'https://images.unsplash.com/photo-1553062407-98eeb64c6a62?w=400', 'Bags'),
('Mechanical Keyboard', 5499.00, 'RGB backlit with tactile switches', 'https://images.unsplash.com/photo-1587829741301-dc798b83add3?w=400', 'Electronics'),
('Sunglasses', 1299.00, 'UV400 protection polarized lenses', 'https://images.unsplash.com/photo-1572635196237-14b3f281503f?w=400', 'Accessories')
ON CONFLICT DO NOTHING;
