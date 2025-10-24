-- Database schema initialization script for the Retail Store application.
--
-- This script creates the required tables for the retail application.  It is
-- executed automatically by the DAO layer on first connection.  You may
-- also apply it manually using the SQLite CLI:
--
--     sqlite3 retail.db < db/init.sql

-- Enable foreign key enforcement
PRAGMA foreign_keys = ON;

-- Users table stores registered users and an admin flag
CREATE TABLE IF NOT EXISTS User (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0
);

-- Products table maintains the product catalogue
CREATE TABLE IF NOT EXISTS Product (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    price REAL NOT NULL,
    stock INTEGER NOT NULL CHECK (stock >= 0),
    -- Optional flash sale fields.  When flash_sale_start and flash_sale_end
    -- denote an active period and flash_sale_price is set, the product will
    -- be sold at the discounted flash_sale_price instead of the regular price.
    flash_sale_price REAL,
    flash_sale_start TEXT,
    flash_sale_end TEXT
);

-- Sales table records completed purchases
CREATE TABLE IF NOT EXISTS Sale (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    subtotal REAL NOT NULL,
    total REAL NOT NULL,
    status TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES User(id)
);

-- SaleItem table records individual line items for each sale
CREATE TABLE IF NOT EXISTS SaleItem (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    FOREIGN KEY (sale_id) REFERENCES Sale(id),
    FOREIGN KEY (product_id) REFERENCES Product(id)
);

-- Payment table records payment details for each sale
CREATE TABLE IF NOT EXISTS Payment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL,
    method TEXT NOT NULL,
    reference TEXT NOT NULL,
    amount REAL NOT NULL,
    status TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (sale_id) REFERENCES Sale(id)
);