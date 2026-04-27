import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from ..forms import ChangerStatutForm, ImportExcelForm, InscritForm, PaiementInscriptionForm
from ..models import Certification, Cohorte, Inscription, Inscrit, Paiement, TypeTarif
from ..notifications import notifier_changement_statut, notifier_inscription
from ._base import _creer_compte_apprenant, _map_columns


@login_required
def inscrits_list(request):
    query = request.GET.get("q", "").strip()
    activite_filter = request.GET.get("activite", "")
    certification_filter = request.GET.get("certification", "")
    statut_filter = request.GET.get("statut", "")

    inscrits = Inscrit.objects.prefetch_related(
        "inscriptions__cohorte__certification", "inscriptions__paiements"
    ).order_by("-date_inscription")

    if query:
        for mot in query.split():
            inscrits = inscrits.filter(
                Q(nom__icontains=mot)
                | Q(prenom__icontains=mot)
                | Q(email__icontains=mot)
                | Q(telephone__icontains=mot)
            )

    if activite_filter:
        inscrits = inscrits.filter(activite=activite_filter)

    if certification_filter:
        inscrits = inscrits.filter(
            inscriptions__cohorte__certification__pk=certification_filter
        ).distinct()

    if statut_filter:
        inscrits = inscrits.filter(inscriptions__statut=statut_filter).distinct()

    filter_certif_ids = request.session.get("filter_certif_ids", [])
    filter_cohorte_ids = request.session.get("filter_cohorte_ids", [])
    if filter_cohorte_ids:
        inscrits = inscrits.filter(inscriptions__cohorte_id__in=filter_cohorte_ids).distinct()
    elif filter_certif_ids:
        inscrits = inscrits.filter(
            inscriptions__cohorte__certification_id__in=filter_certif_ids
        ).distinct()

    certifications_all = Certification.objects.order_by("nom")
    nb_total = Inscrit.objects.count()

    inscrits_avec_compte = list(
        Inscrit.objects.filter(compte_apprenant__isnull=False)
        .prefetch_related(
            Prefetch(
                "inscriptions",
                queryset=Inscription.objects.select_related(
                    "cohorte__certification"
                ).prefetch_related("paiements"),
            )
        )
        .order_by("nom", "prenom")
    )

    list_inscrits_actifs = []
    list_sans_inscription = []
    list_non_paye = []
    list_paiement_attente = []
    inscrits_actifs_pks = set()

    for ins in inscrits_avec_compte:
        inscriptions = list(ins.inscriptions.all())
        if not inscriptions:
            list_sans_inscription.append(ins)
            continue

        is_actif = False
        has_attente = False
        has_non_paye = False

        for ic in inscriptions:
            paiements = list(ic.paiements.all())
            total_confirme = sum(p.montant for p in paiements if p.statut == "confirme")
            has_attente_paiement = any(p.statut == "en_attente" for p in paiements)

            if (
                ic.statut in ("inscrit", "en_formation", "formation_terminee", "certifie")
                and total_confirme >= ic.montant_du
            ):
                is_actif = True
                inscrits_actifs_pks.add(ins.pk)
                break
            if has_attente_paiement:
                has_attente = True
            elif ic.statut == "pre_inscrit":
                has_non_paye = True

        if is_actif:
            list_inscrits_actifs.append(ins)
        elif has_attente:
            list_paiement_attente.append(ins)
        elif has_non_paye:
            list_non_paye.append(ins)
        else:
            list_sans_inscription.append(ins)

    list_pre_inscrits = list_sans_inscription + list_non_paye + list_paiement_attente
    nb_pre_inscrits = len(list_pre_inscrits)
    nb_avec_certif = len(list_inscrits_actifs)

    paginator = Paginator(inscrits, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "inscrits": page_obj,
        "page_obj": page_obj,
        "query": query,
        "activite_filter": activite_filter,
        "certification_filter": certification_filter,
        "statut_filter": statut_filter,
        "certifications_all": certifications_all,
        "statut_choices": Inscription.STATUT_CHOICES,
        "activite_choices": Inscrit.ACTIVITE_CHOICES,
        "active_page": "inscrits",
        "nb_inscrits": nb_total,
        "nb_pre_inscrits": nb_pre_inscrits,
        "nb_avec_certif": nb_avec_certif,
        "list_pre_inscrits": list_pre_inscrits,
        "list_inscrits_actifs": list_inscrits_actifs,
        "list_sans_inscription": list_sans_inscription,
        "list_non_paye": list_non_paye,
        "list_paiement_attente": list_paiement_attente,
    }
    return render(request, "inscriptions/inscrits_list.html", context)


@login_required
def inscrit_detail(request, pk):
    inscrit = get_object_or_404(Inscrit, pk=pk)
    inscriptions = (
        inscrit.inscriptions.select_related("cohorte__certification")
        .prefetch_related("paiements")
        .order_by("-date_inscription")
    )

    statut_forms = {insc.pk: ChangerStatutForm(instance=insc) for insc in inscriptions}
    paiement_forms = {
        insc.pk: PaiementInscriptionForm(initial={"date_paiement": timezone.now().date()})
        for insc in inscriptions
    }

    try:
        compte = inscrit.compte_apprenant
    except Exception:
        compte = None

    context = {
        "inscrit": inscrit,
        "inscriptions": inscriptions,
        "statut_forms": statut_forms,
        "paiement_forms": paiement_forms,
        "compte": compte,
        "active_page": "inscrits",
    }
    return render(request, "inscriptions/inscrit_detail.html", context)


@login_required
def admin_certifications_pour_inscrit(request, pk):
    """Admin: choose which certification to enroll an inscrit in."""
    inscrit = get_object_or_404(Inscrit, pk=pk)
    certifs_actives = Certification.objects.filter(actif=True).order_by("nom")
    certifs_inactives = Certification.objects.filter(actif=False).order_by("nom")
    return render(
        request,
        "inscriptions/admin_certifications_pour_inscrit.html",
        {
            "inscrit": inscrit,
            "certifs_actives": certifs_actives,
            "certifs_inactives": certifs_inactives,
            "active_page": "inscrits",
        },
    )


@login_required
def admin_inscription_directe(request, pk, certif_pk):
    """Admin: enroll an inscrit in a specific certification (choose cohorte)."""
    inscrit = get_object_or_404(Inscrit, pk=pk)
    certification = get_object_or_404(Certification, pk=certif_pk)
    cohortes = Cohorte.objects.filter(certification=certification, actif=True).order_by("nom")

    errors = {}

    if request.method == "POST":
        cohorte_id = request.POST.get("cohorte_id", "").strip()
        action = request.POST.get("action", "payer")
        cohorte = None

        if cohorte_id:
            try:
                cohorte = Cohorte.objects.get(
                    pk=cohorte_id, certification=certification, actif=True
                )
            except Cohorte.DoesNotExist:
                errors["cohorte"] = "Cohorte invalide."
        if not cohorte:
            errors["cohorte"] = "Veuillez sélectionner une session valide."

        if not errors:
            # Choisir le premier type de tarif actif disponible (certif ou option)
            type_tarif = None
            if cohorte.option:
                type_tarif = TypeTarif.objects.filter(option=cohorte.option, actif=True).first()
            if type_tarif is None:
                type_tarif = TypeTarif.objects.filter(
                    certification=certification, actif=True
                ).first()
            montant_du = float(type_tarif.montant) if type_tarif else 0
            inscription, created = Inscription.objects.get_or_create(
                inscrit=inscrit,
                cohorte=cohorte,
                defaults={
                    "statut": "pre_inscrit",
                    "montant_du": montant_du,
                    "type_tarif": type_tarif,
                },
            )
            if created:
                notifier_inscription(inscription)

            if action == "sans_payer":
                messages.success(
                    request,
                    f"{inscrit.nom_complet} inscrit(e) à"
                    f" « {certification.nom} » (paiement différé).",
                )
                return redirect("inscrit_detail", pk=inscrit.pk)
            else:
                request.session["pending_inscription_id"] = inscription.pk
                return redirect("portail_paiement", pk=inscription.pk)

    return render(
        request,
        "inscriptions/admin_inscription_directe.html",
        {
            "inscrit": inscrit,
            "certification": certification,
            "cohortes": cohortes,
            "errors": errors,
            "active_page": "inscrits",
        },
    )


@login_required
def inscrit_ajouter(request):
    if request.method == "POST":
        form = InscritForm(request.POST)
        if form.is_valid():
            inscrit = form.save(commit=False)
            inscrit.source = "manuel"
            inscrit.save()
            try:
                if not hasattr(inscrit, "compte_apprenant"):
                    _, compte = _creer_compte_apprenant(inscrit)
                    messages.success(
                        request,
                        f'Inscrit "{inscrit}" ajouté. Compte portail créé — '
                        f"identifiant : {compte.user.username}"
                        " — mot de passe provisoire : passer01",
                    )
                else:
                    messages.success(request, f'Inscrit "{inscrit}" ajouté avec succès.')
            except Exception:
                messages.success(request, f'Inscrit "{inscrit}" ajouté avec succès.')
            return redirect("inscrit_detail", pk=inscrit.pk)
    else:
        form = InscritForm()

    context = {
        "form": form,
        "titre": "Ajouter un inscrit",
        "action": "Ajouter",
        "active_page": "inscrits",
    }
    return render(request, "inscriptions/inscrit_form.html", context)


@login_required
def admin_creer_compte_inscrit(request, pk):
    """Create a portal account (User + CompteApprenant) for an inscrit who doesn't have one."""
    inscrit = get_object_or_404(Inscrit, pk=pk)
    try:
        _ = inscrit.compte_apprenant
        messages.info(request, f"Un compte portail existe déjà pour {inscrit.nom_complet}.")
        return redirect("inscrit_detail", pk=pk)
    except Exception:
        pass
    _, compte = _creer_compte_apprenant(inscrit)
    messages.success(
        request,
        f"Compte portail créé pour {inscrit.nom_complet} — "
        f"identifiant : {compte.user.username} — mot de passe provisoire : passer01",
    )
    return redirect("inscrit_detail", pk=pk)


@login_required
def inscrit_modifier(request, pk):
    inscrit = get_object_or_404(Inscrit, pk=pk)
    if request.method == "POST":
        form = InscritForm(request.POST, instance=inscrit)
        if form.is_valid():
            form.save()
            messages.success(request, f'Inscrit "{inscrit}" modifié avec succès.')
            return redirect("inscrit_detail", pk=inscrit.pk)
    else:
        form = InscritForm(instance=inscrit)

    context = {
        "form": form,
        "inscrit": inscrit,
        "titre": f"Modifier : {inscrit}",
        "action": "Enregistrer",
        "active_page": "inscrits",
    }
    return render(request, "inscriptions/inscrit_form.html", context)


@login_required
def inscrit_supprimer(request, pk):
    inscrit = get_object_or_404(Inscrit, pk=pk)
    if request.method == "POST":
        nom = str(inscrit)
        inscrit.delete()
        messages.success(request, f'Inscrit "{nom}" supprimé avec succès.')
        return redirect("inscrits_list")

    context = {
        "inscrit": inscrit,
        "active_page": "inscrits",
    }
    return render(request, "inscriptions/inscrit_confirm_delete.html", context)


@login_required
def inscription_wizard(request):
    """3-step wizard: certification → cohorte → inscrit → confirmation."""
    certifications = (
        Certification.objects.filter(actif=True)
        .prefetch_related("types_tarif", "options__types_tarif")
        .order_by("nom")
    )

    # Build tarif data for JS (certif_pk → tarifs/options)
    certif_data = {}
    for c in certifications:
        if c.a_options:
            certif_data[c.pk] = {
                "a_options": True,
                "nom": c.nom,
                "options": {
                    str(opt.pk): {
                        "nom": opt.nom,
                        "tarifs": [
                            {"id": t.pk, "nom": t.nom, "montant": float(t.montant)}
                            for t in opt.types_tarif.filter(actif=True)
                        ],
                    }
                    for opt in c.options.filter(actif=True)
                },
            }
        else:
            certif_data[c.pk] = {
                "a_options": False,
                "nom": c.nom,
                "tarifs": [
                    {"id": t.pk, "nom": t.nom, "montant": float(t.montant)}
                    for t in c.types_tarif.filter(actif=True)
                ],
            }

    if request.method == "POST":
        cohorte_id = request.POST.get("cohorte_id")
        type_tarif_id = request.POST.get("type_tarif_id", "")
        inscrit_id = request.POST.get("inscrit_id")
        statut = request.POST.get("statut", "inscrit")
        notes = request.POST.get("notes", "")
        montant_du = request.POST.get("montant_du", "0")

        def _render_wizard(extra=None):
            ctx = {
                "certifications": certifications,
                "certif_data_json": json.dumps(certif_data),
                "statut_choices": Inscription.STATUT_CHOICES,
                "activite_choices": Inscrit.ACTIVITE_CHOICES,
                "active_page": "inscrits",
            }
            if extra:
                ctx.update(extra)
            return render(request, "inscriptions/inscription_wizard.html", ctx)

        cohorte = None
        if cohorte_id:
            try:
                cohorte = Cohorte.objects.select_related("certification", "option").get(
                    pk=cohorte_id
                )
            except Cohorte.DoesNotExist:
                messages.error(request, "Cohorte invalide.")
                return _render_wizard()

        if not cohorte:
            messages.error(request, "Veuillez sélectionner une cohorte.")
            return _render_wizard()

        # Resolve type_tarif
        type_tarif = None
        if type_tarif_id:
            try:
                type_tarif = TypeTarif.objects.get(pk=type_tarif_id)
            except TypeTarif.DoesNotExist:
                pass
        if type_tarif is None:
            if cohorte.option:
                type_tarif = TypeTarif.objects.filter(option=cohorte.option, actif=True).first()
            else:
                type_tarif = TypeTarif.objects.filter(
                    certification=cohorte.certification, actif=True
                ).first()

        inscrit = None
        if inscrit_id:
            try:
                inscrit = Inscrit.objects.get(pk=inscrit_id)
            except Inscrit.DoesNotExist:
                messages.error(request, "Participant introuvable.")

        if not inscrit:
            nom = request.POST.get("nom", "").strip()
            prenom = request.POST.get("prenom", "").strip()
            email = request.POST.get("email", "").strip().lower()
            telephone = request.POST.get("telephone", "").strip()
            activite = request.POST.get("activite", "etudiant")

            if not nom or not prenom:
                messages.error(request, "Nom et prénom requis pour créer un participant.")
                return _render_wizard()

            if email:
                inscrit, _ = Inscrit.objects.update_or_create(
                    email=email,
                    defaults={
                        "nom": nom,
                        "prenom": prenom,
                        "telephone": telephone,
                        "activite": activite,
                        "source": "manuel",
                    },
                )
            else:
                inscrit = Inscrit.objects.create(
                    nom=nom,
                    prenom=prenom,
                    email=email,
                    telephone=telephone,
                    activite=activite,
                    source="manuel",
                )

        if Inscription.objects.filter(inscrit=inscrit, cohorte=cohorte).exists():
            messages.warning(request, f'"{inscrit}" est déjà inscrit à la cohorte "{cohorte.nom}".')
            return redirect("inscrit_detail", pk=inscrit.pk)

        try:
            montant_du_val = float(montant_du) if montant_du else 0
        except (ValueError, TypeError):
            montant_du_val = 0

        if montant_du_val == 0 and type_tarif:
            montant_du_val = float(type_tarif.montant)

        inscription = Inscription.objects.create(
            inscrit=inscrit,
            cohorte=cohorte,
            statut=statut,
            type_tarif=type_tarif,
            montant_du=montant_du_val,
            notes=notes,
        )
        notifier_inscription(inscription)
        messages.success(
            request,
            f'"{inscrit}" inscrit à la cohorte "{cohorte.nom}" ({cohorte.certification.nom}).',
        )
        return redirect("inscrit_detail", pk=inscrit.pk)

    context = {
        "certifications": certifications,
        "certif_data_json": json.dumps(certif_data),
        "statut_choices": Inscription.STATUT_CHOICES,
        "activite_choices": Inscrit.ACTIVITE_CHOICES,
        "active_page": "inscrits",
    }
    return render(request, "inscriptions/inscription_wizard.html", context)


@login_required
def changer_statut(request, pk):
    inscription = get_object_or_404(Inscription, pk=pk)
    next_url = request.POST.get("next") or request.GET.get("next", "")

    if request.method == "POST":
        form = ChangerStatutForm(request.POST, instance=inscription)
        if form.is_valid():
            form.save()
            notifier_changement_statut(inscription)
            messages.success(
                request,
                f"Statut mis à jour : {inscription.get_statut_display()}.",
            )
    if next_url:
        return redirect(next_url)
    return redirect("inscrit_detail", pk=inscription.inscrit.pk)


@login_required
def inscription_supprimer(request, pk):
    inscription = get_object_or_404(Inscription, pk=pk)
    inscrit_pk = inscription.inscrit.pk

    if request.method == "POST":
        cohorte_nom = inscription.cohorte.nom
        inscription.delete()
        messages.success(request, f'Inscription à la cohorte "{cohorte_nom}" supprimée.')
        return redirect("inscrit_detail", pk=inscrit_pk)

    context = {
        "inscription": inscription,
        "active_page": "inscrits",
    }
    return render(request, "inscriptions/inscription_confirm_delete.html", context)


@login_required
def import_excel(request):
    if request.method == "POST":
        import openpyxl

        form = ImportExcelForm(request.POST, request.FILES)
        if form.is_valid():
            fichier = request.FILES["fichier"]
            cohorte = form.cleaned_data.get("cohorte")

            try:
                wb = openpyxl.load_workbook(fichier, read_only=True, data_only=True)
                ws = wb.active
                rows = list(ws.iter_rows(values_only=True))

                if not rows:
                    messages.error(request, "Le fichier est vide.")
                    return render(
                        request,
                        "inscriptions/import_excel.html",
                        {
                            "form": form,
                            "active_page": "inscrits",
                            "certifications": Certification.objects.filter(actif=True).order_by(
                                "nom"
                            ),
                        },
                    )

                headers = rows[0]
                col_map = _map_columns(headers)

                required = ["nom", "prenom"]
                missing = [f for f in required if f not in col_map]
                if missing:
                    messages.error(
                        request,
                        f'Colonnes obligatoires manquantes : {", ".join(missing)}. '
                        f'Colonnes trouvées : {", ".join(str(h) for h in headers if h)}',
                    )
                    return render(
                        request,
                        "inscriptions/import_excel.html",
                        {
                            "form": form,
                            "active_page": "inscrits",
                            "certifications": Certification.objects.filter(actif=True).order_by(
                                "nom"
                            ),
                        },
                    )

                created = updated = enrolled = paid = 0
                errors = []
                paiement_solde = form.cleaned_data.get("paiement_solde", False)
                moyen_paiement = form.cleaned_data.get("moyen_paiement", "especes")

                for row_idx, row in enumerate(rows[1:], start=2):
                    try:
                        nom = str(row[col_map["nom"]] or "").strip()
                        prenom = str(row[col_map["prenom"]] or "").strip()

                        if not nom or not prenom:
                            errors.append(f"Ligne {row_idx}: nom ou prénom manquant.")
                            continue

                        email = ""
                        if "email" in col_map and row[col_map["email"]]:
                            email = str(row[col_map["email"]]).strip().lower()

                        telephone = ""
                        if "telephone" in col_map and row[col_map["telephone"]]:
                            telephone = str(row[col_map["telephone"]]).strip()

                        activite_val = "etudiant"
                        if "activite" in col_map and row[col_map["activite"]]:
                            raw = str(row[col_map["activite"]]).strip().lower()
                            if "prof" in raw:
                                activite_val = "professionnel"

                        if email:
                            inscrit, was_created = Inscrit.objects.update_or_create(
                                email=email,
                                defaults={
                                    "nom": nom,
                                    "prenom": prenom,
                                    "telephone": telephone,
                                    "activite": activite_val,
                                    "source": "excel",
                                },
                            )
                        else:
                            inscrit = Inscrit.objects.create(
                                nom=nom,
                                prenom=prenom,
                                telephone=telephone,
                                activite=activite_val,
                                source="excel",
                            )
                            was_created = True

                        if was_created:
                            created += 1
                            try:
                                if not hasattr(inscrit, "compte_apprenant"):
                                    _creer_compte_apprenant(inscrit)
                            except Exception:
                                pass
                        else:
                            updated += 1

                        if cohorte:
                            # Utiliser le premier type de tarif actif disponible
                            type_tarif = None
                            if cohorte.option:
                                type_tarif = TypeTarif.objects.filter(
                                    option=cohorte.option, actif=True
                                ).first()
                            if type_tarif is None:
                                type_tarif = TypeTarif.objects.filter(
                                    certification=cohorte.certification, actif=True
                                ).first()
                            montant_du = float(type_tarif.montant) if type_tarif else 0
                            inscription, ic_created = Inscription.objects.get_or_create(
                                inscrit=inscrit,
                                cohorte=cohorte,
                                defaults={
                                    "statut": "inscrit",
                                    "type_tarif": type_tarif,
                                    "montant_du": montant_du,
                                },
                            )
                            if ic_created:
                                enrolled += 1

                            if paiement_solde and montant_du > 0:
                                from django.utils import timezone as tz

                                Paiement.objects.get_or_create(
                                    inscription=inscription,
                                    montant=montant_du,
                                    moyen_paiement=moyen_paiement,
                                    statut="confirme",
                                    defaults={"date_paiement": tz.now().date()},
                                )
                                paid += 1

                    except Exception as exc:
                        errors.append(f"Ligne {row_idx}: erreur — {exc}")

                wb.close()

                if created or updated:
                    msg = f"Import terminé : {created} inscrit(s) créé(s), {updated} mis à jour"
                    if cohorte:
                        msg += f", {enrolled} nouvelle(s) inscription(s) à « {cohorte} »"
                    if paid:
                        msg += f", {paid} paiement(s) enregistré(s)"
                    msg += "."
                    messages.success(request, msg)
                for err in errors[:10]:
                    messages.warning(request, err)
                if len(errors) > 10:
                    messages.warning(request, f"... et {len(errors) - 10} autres erreurs.")

                return redirect("inscrits_list")

            except Exception as exc:
                messages.error(request, f"Erreur lors de la lecture du fichier : {exc}")
    else:
        form = ImportExcelForm()

    context = {
        "form": form,
        "active_page": "inscrits",
        "certifications": Certification.objects.filter(actif=True).order_by("nom"),
    }
    return render(request, "inscriptions/import_excel.html", context)
