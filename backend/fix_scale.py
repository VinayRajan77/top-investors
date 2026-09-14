import os
import psycopg2

def run_fix():
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL not found.")
        return
    conn = psycopg2.connect(url)
    cur = conn.cursor()
    cur.execute("UPDATE portfolios SET reported_value = reported_value / 1000.0 WHERE reported_value > 1000000000000;")
    cur.execute("UPDATE holdings SET value = value / 1000.0 WHERE value > 1000000000000;")
    conn.commit()
    cur.close()
    conn.close()
    print("Database scale corrected successfully!")

if __name__ == "__main__":
    run_fix()
