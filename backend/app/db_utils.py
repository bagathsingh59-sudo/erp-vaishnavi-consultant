"""
Database Utility — Safe CRUD Operations (PostgreSQL)
=====================================================
Provides safe_commit() wrapper for all database write operations.
Catches errors, rolls back, and returns user-friendly error messages.
"""

from app import db
from flask import flash
import logging

logger = logging.getLogger(__name__)


def safe_commit(success_msg=None, error_msg=None):
    """
    Safely commit the current database session.
    On failure: rolls back and flashes an error notification.

    Usage:
        db.session.add(obj)
        if safe_commit('Record saved!'):
            # success
        else:
            # failure — error already flashed

    Args:
        success_msg: Flash message on success (optional)
        error_msg: Custom error message on failure (optional)

    Returns:
        True if commit succeeded, False if failed
    """
    try:
        db.session.commit()
        if success_msg:
            flash(success_msg, 'success')
        return True

    except Exception as e:
        db.session.rollback()
        error_detail = str(e)
        logger.error(f"Database commit failed: {error_detail}")

        # Detect specific error types for clear notifications
        from sqlalchemy.exc import IntegrityError, OperationalError, DataError

        if isinstance(e, IntegrityError):
            if 'unique' in error_detail.lower() or 'duplicate' in error_detail.lower():
                msg = error_msg or 'This record already exists. Please check for duplicates.'
            elif 'foreign key' in error_detail.lower():
                msg = error_msg or 'Cannot save: this record depends on another record that does not exist.'
            elif 'not null' in error_detail.lower() or 'not-null' in error_detail.lower():
                msg = error_msg or 'Required field is missing. Please fill all mandatory fields.'
            else:
                msg = error_msg or f'Data conflict error. Please check your input.'
        elif isinstance(e, OperationalError):
            if 'connect' in error_detail.lower() or 'connection' in error_detail.lower():
                msg = 'Database connection failed. Please try again or contact admin.'
            elif 'locked' in error_detail.lower():
                msg = 'Database is busy. Please wait a moment and try again.'
            elif 'no such table' in error_detail.lower():
                msg = 'Database table missing. Please contact admin to run migrations.'
            elif 'no such column' in error_detail.lower():
                msg = 'Database column missing. Please contact admin to update database.'
            else:
                msg = error_msg or 'Database operation failed. Please try again.'
        elif isinstance(e, DataError):
            msg = error_msg or 'Invalid data format. Please check your input values.'
        else:
            msg = error_msg or 'Failed to save. Please try again.'

        flash(msg, 'danger')
        return False


def safe_delete(obj, success_msg=None, error_msg=None):
    """
    Safely delete an object from the database.

    Usage:
        if safe_delete(employee, 'Employee deleted!'):
            # success

    Args:
        obj: SQLAlchemy model instance to delete
        success_msg: Flash message on success
        error_msg: Custom error message on failure

    Returns:
        True if delete succeeded, False if failed
    """
    try:
        db.session.delete(obj)
        return safe_commit(success_msg, error_msg or 'Failed to delete record.')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Database delete failed: {e}")
        flash(error_msg or 'Failed to delete record. It may be linked to other data.', 'danger')
        return False
