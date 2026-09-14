from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Item
from .serializers import (
    DetailResponseSerializer,
    ItemSerializer,
    LoginRequestSerializer,
    LoginResponseSerializer,
)


class ItemViewSet(viewsets.ModelViewSet):
    queryset = Item.objects.all()
    serializer_class = ItemSerializer
    permission_classes = [IsAuthenticated]


class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        request=LoginRequestSerializer,
        responses={200: LoginResponseSerializer, 401: DetailResponseSerializer},
    )
    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")
        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        login(request, user)
        return Response({"detail": "Logged in.", "username": user.username})


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: DetailResponseSerializer})
    def post(self, request):
        logout(request)
        return Response({"detail": "Logged out."})


ITEM_FORM_FIELDS = ["name", "sku", "description", "category", "quantity", "unit_price"]


class ItemListView(LoginRequiredMixin, ListView):
    model = Item
    template_name = "inventory/item_list.html"
    context_object_name = "items"


class ItemCreateView(LoginRequiredMixin, CreateView):
    model = Item
    fields = ITEM_FORM_FIELDS
    template_name = "inventory/item_form.html"
    success_url = reverse_lazy("item-list")


class ItemUpdateView(LoginRequiredMixin, UpdateView):
    model = Item
    fields = ITEM_FORM_FIELDS
    template_name = "inventory/item_form.html"
    success_url = reverse_lazy("item-list")


class ItemDeleteView(LoginRequiredMixin, DeleteView):
    model = Item
    template_name = "inventory/item_confirm_delete.html"
    success_url = reverse_lazy("item-list")
