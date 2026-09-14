from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView

from .views import ItemCreateView, ItemDeleteView, ItemListView, ItemUpdateView

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="item-list", permanent=False)),
    path("login/", auth_views.LoginView.as_view(template_name="inventory/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("items/", ItemListView.as_view(), name="item-list"),
    path("items/add/", ItemCreateView.as_view(), name="item-add"),
    path("items/<int:pk>/edit/", ItemUpdateView.as_view(), name="item-edit"),
    path("items/<int:pk>/delete/", ItemDeleteView.as_view(), name="item-delete"),
]
