from django.urls import path
from . import views

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),

    # Inscrits
    path('inscrits/', views.inscrits_list, name='inscrits_list'),
    path('inscrits/ajouter/', views.inscrit_ajouter, name='inscrit_ajouter'),
    path('inscrits/import/', views.import_excel, name='import_excel'),
    path('inscrits/<int:pk>/', views.inscrit_detail, name='inscrit_detail'),
    path('inscrits/<int:pk>/modifier/', views.inscrit_modifier, name='inscrit_modifier'),
    path('inscrits/<int:pk>/supprimer/', views.inscrit_supprimer, name='inscrit_supprimer'),
    path('inscrits/<int:pk>/paiement/', views.paiement_ajouter_pour_inscrit, name='paiement_ajouter_pour_inscrit'),

    # Paiements
    path('paiements/', views.paiements_list, name='paiements_list'),
    path('paiements/ajouter/', views.paiement_ajouter, name='paiement_ajouter'),
    path('paiements/<int:pk>/modifier/', views.paiement_modifier, name='paiement_modifier'),
    path('paiements/<int:pk>/supprimer/', views.paiement_supprimer, name='paiement_supprimer'),
]
