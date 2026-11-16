# AI Usage Documentation

## Tools used

- ChatGPT GPT-6: Used to create Flask setup
- Claude: Used as a debugger, general code review, and for assisting in finding possible improvements to make in the code. Also used to restructure the code into the required project layout and apply the review's fixes.

## Key prompts

1. “Compare the Flask fields and SQL queries with my existing MySQL tables. Describe why the Contacts page and Add Job form fail, and identify which references need to change to first_name, last_name, job_title, or posting_url without altering my saved records.”
2. “Using the already existing MySQL database and project folder structure, build Flask routes to add, view, edit, and delete records in all four tables"
3. "Examine the current backend coding and identify any possible improvements that can further be made. Explain the possible benefits of each change"
4. “Rewrite the following assuming this is the project structure required” (followed by the course's required file list)

## What Worked Well

- The table definitions and foreign keys gave the forms a consistent set of fields.
- A shared Flask CRUD pattern and reusable templates avoided repeating nearly identical code across all four sections.
- The matching feature became a small, testable function that normalizes skills, removes duplicates, and lists what the user is missing.

## What I Modified

- Added input validation & Deletion confirmation
- Used column names from preexisting table if already premade rather than the Schema given for assignment as template.

## Lessons Learned

- Verify any AI code usage before running for any errors
- Having AI describe what it plans on doing before actual implementation allows to keep better track of what changes are being made