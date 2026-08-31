from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('calc.urls')),   # ← ADD THIS LINE# keep old routes if needed
    path('api/social/', include('socialintel.urls')),
]