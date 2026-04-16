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

    # Survey
    path('serial-number/',           views.api_serial_number,      name='api_serial_number'),
    path('save-survey/',             views.api_save_survey,        name='api_save_survey'),
    path('save-future-voters/',      views.api_save_future_voters,   name='api_save_future_voters'),
    path('save-deceased/',           views.api_save_deceased,        name='api_save_deceased'),

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
    
    # Add these two lines to api/urls.py urlpatterns list:
    
    path('update-voter/',  views.api_update_voter,  name='api_update_voter'),
    path('update-survey/', views.api_update_survey, name='api_update_survey'),
    path('large-families/', views.api_large_families, name='api_large_families'),
    
    # Wards
    path('wards/',                   views.api_wards,              name='api_wards'),
]