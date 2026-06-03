-- Run this to set up the database
CREATE DATABASE IF NOT EXISTS ecommerce;
USE ecommerce;

CREATE TABLE IF NOT EXISTS products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    description TEXT,
    image_url VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'user',
    address TEXT,
    city VARCHAR(100),
    pin VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cart_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    UNIQUE KEY user_product (user_id, product_id)
);

-- Sample products
INSERT INTO products (id, name, price, description, image_url) VALUES
(1, 'Wireless Headphones', 2999.00, 'Premium sound quality with 30hr battery life', 'https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=400'),
(2, 'Running Shoes', 3499.00, 'Lightweight and breathable for daily runs', 'https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=400'),
(3, 'Smart Watch', 8999.00, 'Fitness tracker with heart rate monitor', 'https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=400'),
(4, 'Laptop Backpack', 1799.00, 'Water-resistant with USB charging port', 'https://images.unsplash.com/photo-1553062407-98eeb64c6a62?w=400'),
(5, 'Mechanical Keyboard', 5499.00, 'RGB backlit with tactile switches', 'https://images.unsplash.com/photo-1587829741301-dc798b83add3?w=400'),
(6, 'Sunglasses', 1299.00, 'UV400 protection polarized lenses', 'https://images.unsplash.com/photo-1572635196237-14b3f281503f?w=400')
ON DUPLICATE KEY UPDATE name=VALUES(name), price=VALUES(price), description=VALUES(description), image_url=VALUES(image_url);

-- Sample users (admin/admin123 and user1/user123)
INSERT INTO users (id, username, password, role, address, city, pin) VALUES
(1, 'admin', 'scrypt:32768:8:1$REyo9cfeIa85Dhkm$3dcb96b2176d17a1195ea7a79c9bcae9e883da0fb75b583b14faf9cc7b81157606220fe48d24b0a94b47c6802cecb499fee4603f30647284671b676c2ce5ac2b', 'admin', NULL, NULL, NULL),
(2, 'user1', 'scrypt:32768:8:1$LEsofmIrPbyvT4wE$8af03bd61a7d77dd74bb9bb0aab001203ecba5761cb8844746e3d318378d16d101e1f669fd78e3867c3c9debb8c85919b0e6c61278cc62356b648ad6cfeb4d98', 'user', NULL, NULL, NULL)
ON DUPLICATE KEY UPDATE username=VALUES(username), password=VALUES(password), role=VALUES(role);
