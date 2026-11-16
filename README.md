# Job Application Tracker

A local Flask and MySQL app for tracking companies, job listings, applications, and contacts. The frontend uses plain HTML and CSS.

## Project structure

```
job_tracker/
├── app.py            # Flask routes, table definitions, validation, job matching
├── database.py       # MySQL settings, connection pool and query helpers
├── templates/        # base.html, dashboard.html, companies.html, jobs.html,
│                     # applications.html, contacts.html, job_match.html
├── static/style.css
├── schema.sql        # Database creation script
├── AI_USAGE.md       # GenAI documentation
├── README.md
└── requirements.txt
```

## Setup on Windows

1. Install Python (3.10 or later) and start your MySQL server (8.0.16 or later is recommended).
2. If you already have the assignment's `job_tracker` schema, keep it. Back up any existing data before trying edit or delete actions. For a fresh installation, open and run `schema.sql` in MySQL Workbench.
3. Open `database.py` and set `DB_USER` and `DB_PASSWORD` near the top to your MySQL username and password (`root` is used as a placeholder for both). Change `DB_HOST`, `DB_PORT` or `DB_NAME` there too if yours differ.
4. Open Command Prompt in the folder that contains `app.py` and run:

   ```
   python -m pip install -r requirements.txt
   python app.py
   ```

5. Open http://127.0.0.1:5000.
6. To stop Flask, press Ctrl+C in Command Prompt.

## Using the app

- Dashboard shows counts for all four tables (each links to its list) and applications grouped by status.
- Companies, Jobs, Applications, and Contacts each have a searchable, paged list (25 per page), a detail view, add and edit forms, and a delete confirmation page.
- Create companies before jobs and contacts. Create a job before adding an application to it. Those links are required.
- The database prevents deletion of a company or job while another row references it. Remove or reassign those records first.
- Salaries accept up to two decimal places (up to 99,999,999.99). The maximum salary cannot be lower than the minimum.
- In a job's Requirements (JSON) field, enter an object such as `{"skills":["Python","SQL","Flask"]}`. Job Match divides the number of matching required skills by the number of distinct required skills and displays a whole-number percent. Comparison ignores capitalization, spaces, dots, dashes, and underscores (so `Node.js` matches `nodejs`). Jobs without a usable skill list are skipped, and the page says how many.
- The optional application Interview data (JSON) field can hold information such as `{"round":1,"notes":"Phone screening"}`.