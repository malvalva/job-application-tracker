-- Fresh-install schema for the Flask Job Application Tracker.
-- This script does not drop, rename, or alter existing tables.
-- Required relationships: select a company for jobs and contacts,
-- and select a job for applications.
-- Requires MySQL 8.0.16 or later (CHECK constraints are enforced from that version).

CREATE DATABASE IF NOT EXISTS job_tracker
    CHARACTER SET utf8mb4;

USE job_tracker;

CREATE TABLE IF NOT EXISTS companies (
    company_id INT AUTO_INCREMENT PRIMARY KEY,
    company_name VARCHAR(100) NOT NULL,
    industry VARCHAR(50),
    website VARCHAR(200),
    city VARCHAR(50),
    state VARCHAR(50),
    notes TEXT,
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_company_name (company_name),
    INDEX idx_company_industry (industry)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS jobs (
    job_id INT AUTO_INCREMENT PRIMARY KEY,
    company_id INT NOT NULL,
    job_title VARCHAR(100) NOT NULL,
    job_description TEXT,
    salary_min DECIMAL(10,2),
    salary_max DECIMAL(10,2),
    job_type VARCHAR(20),
    posting_url VARCHAR(500),
    date_posted DATE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    requirements JSON,
    INDEX idx_job_title (job_title),
    INDEX idx_company_type (company_id, job_type),
    CONSTRAINT fk_jobs_company
        FOREIGN KEY (company_id) REFERENCES companies (company_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_jobs_salary
        CHECK (salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max),
    CONSTRAINT chk_jobs_type
        CHECK (job_type IS NULL OR job_type IN ('Full-time', 'Part-time', 'Contract', 'Internship'))
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS applications (
    application_id INT AUTO_INCREMENT PRIMARY KEY,
    job_id INT NOT NULL,
    application_date DATE NOT NULL,
    status VARCHAR(30) DEFAULT 'Applied',
    resume_version VARCHAR(50),
    cover_letter_sent BOOLEAN DEFAULT FALSE,
    response_date DATE,
    interview_date DATETIME,
    notes TEXT,
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    interview_data JSON,
    INDEX idx_app_status (status),
    INDEX idx_app_date (application_date),
    CONSTRAINT fk_applications_job
        FOREIGN KEY (job_id) REFERENCES jobs (job_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_applications_status
        CHECK (status IS NULL OR status IN
               ('Applied', 'Screening', 'Interview', 'Offer', 'Rejected', 'Withdrawn'))
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS contacts (
    contact_id INT AUTO_INCREMENT PRIMARY KEY,
    company_id INT NOT NULL,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    email VARCHAR(100),
    phone VARCHAR(20),
    job_title VARCHAR(100),
    linkedin_url VARCHAR(200),
    notes TEXT,
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_contact_name (last_name, first_name),
    CONSTRAINT fk_contacts_company
        FOREIGN KEY (company_id) REFERENCES companies (company_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;
