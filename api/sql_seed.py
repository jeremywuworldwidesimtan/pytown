import sqlite3

# Create a local SQLite database
conn = sqlite3.connect('api/database.db')

# Create a table for towns
# Town Fields: ID, Name, Size, Specialization, Population, Density, Area (sq km), Established Year, Abandoned Year, Terrain, X Coordinate, Y Coordinate
# Drop table first to avoid duplicates
conn.execute('DROP TABLE IF EXISTS towns')

conn.execute('''CREATE TABLE IF NOT EXISTS towns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    size TEXT,
    specialization TEXT,
    population INTEGER,
    density REAL,
    area REAL,
    established_year INTEGER,
    abandoned_year INTEGER,
    terrain TEXT,
    x_coordinate REAL,
    y_coordinate REAL
)''')

# Load csv data into the towns table
import csv

with open('csv/town_data_1024.csv', 'r') as f:
    reader = csv.reader(f)
    next(reader)  # Skip the header row
    for row in reader:
        insert_row = (
            row[0],  # name
            row[1],  # size
            row[2],  # specialization
            row[3],  # population
            row[4],  # density
            row[5],  # area
            row[9],  # established_year
            row[10],  # abandoned_year
            row[11],  # terrain
            row[12],  # x_coordinate
            row[13]  # y_coordinate
        )
        conn.execute('INSERT INTO towns (name, size, specialization, population, density, area, established_year, abandoned_year, terrain, x_coordinate, y_coordinate) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', insert_row)

# Commit the changes and close the connection
conn.commit()
conn.close()