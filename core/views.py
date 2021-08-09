from django.shortcuts import render, redirect, reverse, get_object_or_404
from .models import Payment, File, Product
from .forms import ProductForm, ProductEmailForm
from django.views import generic
from django.views.generic.detail import SingleObjectMixin
from hitcount.views import HitCountDetailView
from django.http.response import Http404, HttpResponse, JsonResponse
from .blockonomics_utils import create_payment, exchanged_rate, exchanged_rate_to_usd
import requests
import json
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator
from .utils import zipFiles, email_helper, create_payment_helper, check_session_validity
from django.db.models import Prefetch
from datetime import datetime, timedelta

# Create your views here.


# =========================================================== Seller View ===================================================


class ProductCreateView(generic.View):
    form_class = ProductForm
    template_name = "index.html"

    def post(self, request, *args, **kwargs):
        product_form = self.form_class(request.POST or None)
        if product_form.is_valid():
            product = product_form.save()
            for _file in request.FILES.getlist("files"):
                file_obj = File.objects.create(
                    product=product, file_data=_file.file.read(), file_name=_file.name
                )
                request.session["product_id"] = product.pk
            return redirect(reverse("core:product_seller_email_updates"))
        else:
            return render(
                request, self.template_name, context={"errors": product_form.errors}
            )

    def get(self, request, *args, **kwargs):
        return render(request, "index.html")


class ProductEmailUpdatesView(generic.View):
    template_name = "sell-email.html"
    model = Product
    form_class = ProductEmailForm
    email_template = "emails/product_page.html"
    email_subject = "emails/product_page.txt"
    extra_email_context = {}

    def get_object(self, **kwargs):
        return get_object_or_404(
            Product, pk=self.request.session.get("product_id", None)
        )

    def get_context_data(self, **kwargs):
        product = self.get_object(**kwargs)
        context = {}
        context["object"] = product
        context["public_uri"] = self.request.build_absolute_uri(
            reverse("core:product_info_buyer", kwargs={"uid": context["object"].uid})
        )
        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        return render(request, self.template_name, context=context)

    def post(self, request, *args, **kwargs):
        product = self.get_object(**kwargs)
        product_form = self.form_class(request.POST, instance=product)
        context = self.get_context_data(**kwargs)
        
        if product_form.is_valid():
            product_form.save()
        else:
            context["errors"] = product_form.errors
            return render(
                request, self.template_name, context=context
            )

        
        self.extra_email_context["track_uri"] = self.request.build_absolute_uri(
            reverse("core:product_info_seller", kwargs={"token": product.token})
        )
        self.extra_email_context["public_uri"] = self.request.build_absolute_uri(
            reverse("core:product_info_buyer", kwargs={"uid": context["object"].uid})
        )
        email_helper(
            request,
            product.email,
            self.email_subject,
            self.email_template,
            html_email_template_name=self.email_template,
            extra_email_context=self.extra_email_context,
        )
        return redirect(
            reverse("core:product_info_seller", kwargs={"token": product.token})
        )


class ProductSellerView(generic.DetailView):
    template_name = "pymnt-dash.html"
    model = Product

    def get_object(self, **kwargs):
        products = Product.objects.filter(token=self.kwargs.get("token"))
        if not products.exists():
            raise Http404("Product with given token does not exist")

        product = products.prefetch_related("payments").first()
        return product

    def get_context_data(self, **kwargs):
        context = super(ProductSellerView, self).get_context_data(**kwargs)
        context["btc_balance"] = context["object"].btc_balance
        # context["bch_balance"]=context["object"].bch_balance
        context["public_uri"] = self.request.build_absolute_uri(
            reverse("core:product_info_buyer", kwargs={"uid": context["object"].uid})
        )
        context["payments"] = context["object"].payments.filter(
            status_of_transaction=Payment.StatusChoices.CONFIMED
        )
        return context


# ===================================================== BUYER VIEW ============================================


class ProductPublicView(HitCountDetailView):
    count_hit = True
    template_name = "buyerLanding.html"
    model = Product

    def get_object(self, **kwargs):
        return get_object_or_404(Product, uid=self.kwargs.get("uid"))

    def get_context_data(self, **kwargs):
        context = super(ProductPublicView, self).get_context_data(**kwargs)
        context["usd_price"] = str(self.object.price)
        context["bits"] = exchanged_rate(self.object.price, "BTC", self.object.currency)
        context["btc_price"] = context["bits"]/pow(10, 8)
        product = get_object_or_404(Product, uid=self.kwargs.get("uid"))
        payment = create_payment_helper(self.request, product, "BTC", self.object.price)
        context["order_id"] = payment.order_id
        # context["bch_price"]=str(exchanged_rate(self.object.price,"BTC",self.object.currency))[:6]
        return context


class IntializePayment(generic.View):
    template_name = "buyerPay.html"

    @method_decorator(never_cache)
    def get(self, request, *args, **kwargs):
        # product = get_object_or_404(Product, uid=kwargs["uid"])
        crypto = request.GET.get("crypto", None)
        # if crypto not in ["BTC","BCH"]:
        if crypto not in ["BTC"]:
            return HttpResponse("Invalid crypto currency,please use BTC", status=400)

        address, expected_value, payment, usd_price = None, None, None, None
        try:
            payment = get_object_or_404(Payment, order_id=kwargs["order_id"])
            product = payment.product
            address = payment.address
            expected_value = float(payment.expected_value)
            usd_price = float(payment.usd_price)
            request.session["last_order"] = datetime.now().timestamp()
        except (ValueError, Http404, KeyError) as e:  # invalid session
            return HttpResponse(e.response.text)
        except requests.exceptions.RequestException as e:  # Exception at blockonomics api
            return HttpResponse(e.response.text)
        except Exception as e:
            repr(e)
            return HttpResponse("Some error occured please try again", status=400)

        request.session["payment"] = {
            "address": address,
            "expected_value": expected_value,
            "product": product.pk,
            "payment_id": payment.id,
        }
        request.session.modified = True 
        context = {
            "address": address,
            "expected_value": expected_value,
            "usd_price": usd_price,
            "crypto": crypto,
            "last_order": request.session["last_order"],
            "payment_id": payment.id,
        }

        return render(request, self.template_name, context=context)


class PaymentConfirmCallbackView(generic.View):
    def post(self, request, *args, **kwargs):
        data = json.loads(request.body)
        status_of_transaction = data.get("status", None)
        payment_id = data.get("payment_id", None)
        if status_of_transaction is None or payment_id is None:
            return HttpResponse("Invalid data", status=400)

        payment = get_object_or_404(Payment, pk=int(payment_id))

        if status_of_transaction >= payment.status_of_transaction:
            payment.status_of_transaction = max(
                payment.status_of_transaction, status_of_transaction
            )
            payment.save()
            return redirect(
                reverse(
                    "core:payment_info_buyer", kwargs={"order_id": payment.order_id}
                )
            )

        return HttpResponse("Payment status isn't changed")


class PaymentStatusView(generic.View):
    payment_status_view = {
        0: "confirmation.html",
        1: "confirmation.html",
        2: "payStatus.html",
    }

    def get_payment(self, **kwargs):
        payment = get_object_or_404(Payment, order_id=self.kwargs.get("order_id"))
        return payment

    @method_decorator(never_cache)
    def get(self, request, *args, **kwargs):
        payment = self.get_payment(**kwargs)

        if payment.rbf == False:
            status_of_view = 2
        else:
            status_of_view = payment.status_of_transaction

        context = {
            "payment": payment,
            "download_uri": request.build_absolute_uri(
                reverse(
                    "core:payment_info_buyer", kwargs={"order_id": payment.order_id}
                )
            ),
        }
        return render(
            request,
            self.payment_status_view[status_of_view],
            context=context,
        )


class DownloadFiles(generic.View):
    def get_payment(self, **kwargs):
        payments = Payment.objects.filter(order_id=kwargs["order_id"])
        if not payments.exists():
            raise Http404("Payment with given order id does not exist")

        payment = (
            payments.select_related("product")
            .prefetch_related(
                Prefetch(
                    "product__files",
                    queryset=File.objects.filter(
                        product__payments__order_id=kwargs["order_id"]
                    ),
                    to_attr="files_list",
                )
            )
            .first()
        )
        return payment

    def get(self, request, *args, **kwargs):

        payment = self.get_payment(**kwargs)

        try:
            if payment.status_of_transaction == 2 or payment.rbf == False:
                files = payment.product.files_list
                zipped_file = zipFiles(files)
                response = HttpResponse(
                    zipped_file, content_type="application/octet-stream"
                )
                response[
                    "Content-Disposition"
                ] = f"attachment; filename={payment.product.product_name}.zip"
                return response
            else:
                return HttpResponse("Payment is being processed")
        except KeyError:
            return HttpResponse("Session may have expired try refreshing", status=400)
        except Exception as e:
            repr(e)
            return HttpResponse(repr(e), status=400)


class UpdatePaymentStatusCallback(generic.View):
    email_template = "emails/payment.html"
    email_subject = "emails/product_page.txt"
    extra_email_context = {}

    def get(self, request, *args, **kwargs):
        payment = get_object_or_404(Payment, address=request.GET["addr"])
        payment.status_of_transaction = max(
            payment.status_of_transaction, int(request.GET["status"])
        )
        payment.txid = request.GET["txid"]
        if int(request.GET["status"]) == 2:
            payment.received_value = float(request.GET["value"]) / 1e8
            self.extra_email_context["track_uri"] = self.request.build_absolute_uri(
                reverse(
                    "core:product_info_seller", kwargs={"token": payment.product.token}
                )
            )
            email_helper(
                request,
                payment.product.email,
                self.email_subject,
                self.email_template,
                html_email_template_name=self.email_template,
                extra_email_context=self.extra_email_context,
            )


        if request.GET.get("rbf") is not None and int(request.GET["rbf"]) == 1:
            payment.rbf = True
        elif request.GET.get("rbf") is None and int(request.GET["status"]) != 0:
            pass
        else:
            payment.rbf = False

        payment.save()
        return HttpResponse(200)
