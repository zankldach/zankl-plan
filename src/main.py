# ----------------------------
# Week view (sichere Version)
# ----------------------------
@app.get("/", response_class=HTMLResponse)
@app.get("/week", response_class=HTMLResponse)
def week(request: Request, kw: int = 1, year: int = 2025, standort: str = "engelbrechts"):
    conn = get_conn()
    cur = conn.cursor()

    try:
        # Plan abrufen oder erstellen
        cur.execute("""
            SELECT id,row_count FROM week_plans
            WHERE year=? AND kw=? AND standort=?
        """, (year, kw, standort))
        plan = cur.fetchone()

        if not plan:
            cur.execute("""
                INSERT INTO week_plans(year,kw,standort,row_count)
                VALUES(?,?,?,5)
            """, (year, kw, standort))
            conn.commit()
            plan_id = cur.lastrowid
            rows = 5
        else:
            plan_id = plan["id"]
            rows = plan["row_count"]

        # Grid vorbereiten mit sicherer Indexprüfung
        grid = [[{"text": ""} for _ in range(5)] for _ in range(rows)]
        cur.execute("""
            SELECT row_index, day_index, text
            FROM week_cells
            WHERE week_plan_id=?
        """, (plan_id,))
        for r in cur.fetchall():
            row = r["row_index"]
            day = r["day_index"]
            if 0 <= row < rows and 0 <= day < 5:
                grid[row][day]["text"] = r["text"]

        # Mitarbeiter für diesen Standort
        cur.execute("SELECT id,name FROM employees WHERE standort=? ORDER BY id", (standort,))
        employees = [{"id": e["id"], "name": e["name"]} for e in cur.fetchall()]

        # Default-Tage (optional: dynamisch aus Kalender)
        days = [
            {"label":"Montag","date":"06.01"},
            {"label":"Dienstag","date":"07.01"},
            {"label":"Mittwoch","date":"08.01"},
            {"label":"Donnerstag","date":"09.01"},
            {"label":"Freitag","date":"10.01"},
        ]

        return templates.TemplateResponse("week.html", {
            "request": request,
            "grid": grid,
            "employees": employees,
            "kw": kw,
            "year": year,
            "days": days,
            "standort": standort
        })

    except Exception as e:
        # Fehlerausgabe für Render Logs
        print("Fehler in /week:", e)
        return HTMLResponse(f"<h1>Fehler beim Laden der Woche</h1><pre>{e}</pre>", status_code=500)
    finally:
        conn.close()
