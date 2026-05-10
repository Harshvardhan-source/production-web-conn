# ── Add these lines to your existing urls.py urlpatterns list ────────────────
#
# from . import views   ← already present
#
#   # AI Chat — document-aware Anthropic chat
#   path('ai/chat/',         views.api_ai_chat,         name='api_ai_chat'),
#   path('ai/chat/export/',  views.api_ai_chat_export,  name='api_ai_chat_export'),
#   path('ai/data-files/',   views.api_ai_data_files,   name='api_ai_data_files'),
#
# ─────────────────────────────────────────────────────────────────────────────
# Full urls.py with new routes added (safe to replace your existing file)
# ─────────────────────────────────────────────────────────────────────────────

from django.urls import path
from . import views

urlpatterns = [
    # Auth
    path('csrf/',                    views.get_csrf,               name='get_csrf'),
    path('me/',                      views.api_me,                 name='api_me'),
    path('register/',                views.api_register,           name='api_register'),
    path('login/',                   views.api_login,              name='api_login'),
    path('logout/',                  views.api_logout,             name='api_logout'),

    # Dashboard
    path('dashboard/',               views.api_dashboard,          name='api_dashboard'),
    path('ward-dashboard/',          views.api_ward_dashboard,     name='api_ward_dashboard'),
    path('booth-dashboard/',         views.api_booth_dashboard,    name='api_booth_dashboard'),

    # Survey
    path('serial-number/',           views.api_serial_number,      name='api_serial_number'),
    path('save-survey/',             views.api_save_survey,        name='api_save_survey'),
    path('save-future-voters/',      views.api_save_future_voters, name='api_save_future_voters'),
    path('save-deceased/',           views.api_save_deceased,      name='api_save_deceased'),

    # Schemes
    path('scheme-voter-list/',       views.api_scheme_voter_list,  name='api_scheme_voter_list'),
    path('view-scheme/',             views.api_view_scheme,        name='api_view_scheme'),

    # Data
    path('data/',                    views.api_data_view,          name='api_data_view'),
    path('upload-voter-list/',       views.api_upload_voter_list,  name='api_upload_voter_list'),

    # Voters
    path('voters/',                  views.api_voter_search,       name='api_voter_search'),
    path('voter-family/',            views.api_voter_family,       name='api_voter_family'),
    path('house-search/',            views.api_house_search,       name='api_house_search'),

    # SIR — Summary Intensive Revision
    path('sir/check/',               views.api_check_sir,          name='api_check_sir'),
    path('sir-data/',                views.api_sir_data,           name='api_sir_data'),
    path('sir-bulk/',                views.api_sir_bulk,           name='api_sir_bulk'),
    path('sir/records/',             views.api_sir_records,        name='api_sir_records'),
    path('sir/stats/',               views.api_sir_stats,          name='api_sir_stats'),

    path('update-voter/',            views.api_update_voter,       name='api_update_voter'),
    path('update-survey/',           views.api_update_survey,      name='api_update_survey'),
    path('large-families/',          views.api_large_families,     name='api_large_families'),

    # Wards
    path('wards/',                   views.api_wards,              name='api_wards'),

    # Admin — role management & approvals (MLA / PA only)
    path('admin/users/',             views.api_admin_users,        name='api_admin_users'),
    path('admin/approve/',           views.api_admin_approve,      name='api_admin_approve'),
    path('admin/reject/',            views.api_admin_reject,       name='api_admin_reject'),
    path('admin/update-role/',       views.api_admin_update_role,  name='api_admin_update_role'),
    path('api/admin/disable/',       views.api_admin_disable,      name='admin_disable'),
    path('api/admin/enable/',        views.api_admin_enable,       name='admin_enable'),

    # Survey Progress & Location Tracking (Admin only)
    path('admin/survey-progress/',   views.api_admin_survey_progress,  name='api_admin_survey_progress'),
    path('location/ping/',           views.api_location_ping,          name='api_location_ping'),
    path('admin/locations/',         views.api_admin_locations,        name='api_admin_locations'),
    path('admin/location-dates/',    views.api_admin_location_dates,   name='api_admin_location_dates'),

    # ML Intelligence
    path('ml/constituency-swot/',    views.api_ml_constituency_swot,  name='api_ml_constituency_swot'),

    # AI Insights (existing)
    path('ai/query-insight/',        views.api_ai_query_insight,      name='api_ai_query_insight'),
    path('ai/birdseye-view/',        views.api_ai_birdseye_view,      name='api_ai_birdseye_view'),

    # ── AI Chat — NEW ─────────────────────────────────────────────────────────
    path('ai/chat/',                 views.api_ai_chat,               name='api_ai_chat'),
    path('ai/chat/export/',          views.api_ai_chat_export,        name='api_ai_chat_export'),
    path('ai/data-files/',           views.api_ai_data_files,         name='api_ai_data_files'),
    path('ward-places/',             views.api_ward_places,           name='api_ward_places'),
]