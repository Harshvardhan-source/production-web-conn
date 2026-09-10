from django.urls import path

from . import views

urlpatterns = [
    path('overview/',      views.api_social_overview,     name='api_social_overview'),
    path('feed/',          views.api_social_feed,         name='api_social_feed'),
    path('post/<str:post_id>/', views.api_social_post_detail, name='api_social_post_detail'),
    path('swot/',          views.api_social_swot,         name='api_social_swot'),
    path('outrage/',       views.api_social_outrage,      name='api_social_outrage'),
    path('report/',        views.api_social_report,       name='api_social_report'),
    path('jobs/status/',   views.api_social_jobs_status,  name='api_social_jobs_status'),
    path('sync/',          views.api_social_sync,         name='api_social_sync'),
    path('sources/',       views.api_social_sources,      name='api_social_sources'),
]
