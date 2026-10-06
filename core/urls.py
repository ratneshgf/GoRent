from django.urls import include, path
from rest_framework.routers import DefaultRouter
from . import views as v
router = DefaultRouter(trailing_slash=False)
router.register("vehicles", v.VehicleViewSet, basename="vehicle")
router.register("bookings", v.BookingViewSet, basename="booking")
urlpatterns = [
    path("auth/register", v.RegisterView.as_view()), path("auth/login", v.LoginView.as_view()), path("auth/logout", v.LogoutView.as_view()),
    path("users/me", v.MeView.as_view()), path("owner/identity", v.OwnerIdentityView.as_view()), path("renter/identity", v.RenterIdentityView.as_view()), path("reviews", v.ReviewCreate.as_view()),
    path("", include(router.urls)),
]
