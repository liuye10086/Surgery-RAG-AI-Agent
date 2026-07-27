-- Migration: Add safety_flags column to audit_logs
-- Date: 2026-07-22
-- Description: Records content filter hits (input blocked, danger symptoms, output flags)
--              for compliance auditing of safety filter actions.

ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS safety_flags JSONB DEFAULT '{}';
