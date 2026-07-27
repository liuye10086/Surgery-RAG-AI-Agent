-- Migration: Add is_no_knowledge column to messages table
-- Date: 2026-07-20
-- Description: Supports tracking whether an assistant response was flagged
--              as "no knowledge found in the knowledge base".

ALTER TABLE messages ADD COLUMN IF NOT EXISTS is_no_knowledge BOOLEAN DEFAULT FALSE;
