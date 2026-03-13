"""
URL configuration for myapp project.
Routes for load-testing endpoints and metrics.
"""
from django.urls import path
from myapp import views

urlpatterns = [
    path('api/health/', views.health_check, name='health'),
    path('api/cpu-heavy/', views.cpu_heavy, name='cpu_heavy'),
    path('api/io-heavy/', views.io_heavy, name='io_heavy'),
    path('api/mixed/', views.mixed_workload, name='mixed'),
    path('api/metrics/', views.worker_metrics, name='metrics'),
]
