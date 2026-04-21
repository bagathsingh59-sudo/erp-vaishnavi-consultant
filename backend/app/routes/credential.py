from flask import Blueprint, render_template, request, redirect, url_for, flash
from app import db
from app.models.establishment import Establishment, PortalCredential
from app.user_context import verify_est_ownership

credential_bp = Blueprint('credential', __name__)

# Common portal options for the dropdown
PORTAL_OPTIONS = [
    'EPF (Unified Portal)',
    'ESIC Portal',
    'Shram Suvidha Portal',
    'TRACES (TDS)',
    'GST Portal',
    'Income Tax Portal',
    'MCA (Company Affairs)',
    'Labour Department',
    'Professional Tax Portal',
    'Other'
]


@credential_bp.route('/establishments/<int:est_id>/credentials/add', methods=['GET', 'POST'])
def credential_add(est_id):
    """Add new credential for an establishment"""
    establishment = Establishment.query.get_or_404(est_id)
    verify_est_ownership(establishment)

    if request.method == 'POST':
        portal_name = request.form.get('portal_name', '').strip()
        # If "Other" is selected, use the custom portal name
        if portal_name == 'Other':
            custom_name = request.form.get('custom_portal_name', '').strip()
            portal_name = custom_name if custom_name else 'Other'

        credential = PortalCredential(
            establishment_id=est_id,
            portal_name=portal_name,
            username=request.form.get('username', '').strip(),
            password=request.form.get('password', '').strip(),
            remarks=request.form.get('remarks', '').strip() or None
        )

        db.session.add(credential)
        db.session.commit()
        flash(f'Portal credential for "{portal_name}" added successfully!', 'success')
        return redirect(url_for('establishment.establishment_view', id=est_id))

    return render_template('establishments/credential_form.html',
                           est=establishment,
                           credential=None,
                           mode='add',
                           portal_options=PORTAL_OPTIONS)


@credential_bp.route('/establishments/<int:est_id>/credentials/<int:cred_id>/edit', methods=['GET', 'POST'])
def credential_edit(est_id, cred_id):
    """Edit a credential"""
    establishment = Establishment.query.get_or_404(est_id)
    verify_est_ownership(establishment)
    credential = PortalCredential.query.get_or_404(cred_id)

    if credential.establishment_id != est_id:
        flash('Invalid credential.', 'danger')
        return redirect(url_for('establishment.establishment_view', id=est_id))

    if request.method == 'POST':
        portal_name = request.form.get('portal_name', '').strip()
        if portal_name == 'Other':
            custom_name = request.form.get('custom_portal_name', '').strip()
            portal_name = custom_name if custom_name else 'Other'

        credential.portal_name = portal_name
        credential.username = request.form.get('username', '').strip()
        credential.password = request.form.get('password', '').strip()
        credential.remarks = request.form.get('remarks', '').strip() or None

        db.session.commit()
        flash(f'Credential for "{portal_name}" updated successfully!', 'success')
        return redirect(url_for('establishment.establishment_view', id=est_id))

    return render_template('establishments/credential_form.html',
                           est=establishment,
                           credential=credential,
                           mode='edit',
                           portal_options=PORTAL_OPTIONS)


@credential_bp.route('/establishments/<int:est_id>/credentials/<int:cred_id>/delete', methods=['POST'])
def credential_delete(est_id, cred_id):
    """Delete a credential"""
    establishment = Establishment.query.get_or_404(est_id)
    verify_est_ownership(establishment)
    credential = PortalCredential.query.get_or_404(cred_id)

    if credential.establishment_id != est_id:
        flash('Invalid credential.', 'danger')
        return redirect(url_for('establishment.establishment_view', id=est_id))

    portal_name = credential.portal_name
    db.session.delete(credential)
    db.session.commit()
    flash(f'Credential for "{portal_name}" deleted.', 'warning')
    return redirect(url_for('establishment.establishment_view', id=est_id))
