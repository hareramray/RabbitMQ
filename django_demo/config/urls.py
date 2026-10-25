from django.urls import path
from orders import views

urlpatterns = [
    path("health/", views.health),
    path("api/orders/", views.create_order),
    path("api/orders/<int:order_id>/", views.order_detail),
]
