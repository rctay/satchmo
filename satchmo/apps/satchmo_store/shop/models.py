"""
Configuration items for the shop.
Also contains shopping cart and related classes.
"""

from decimal import Decimal, ROUND_CEILING
from django.conf import settings
from django.contrib.sites.models import Site
from django.contrib.sites.models import Site
from django.core import urlresolvers
from django.db import models
from django.utils.encoding import force_unicode
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext, ugettext_lazy as _
from l10n.models import Country
from l10n.utils import moneyfmt
from livesettings import ConfigurationSettings, config_value, config_choice_values
from payment.fields import PaymentChoiceCharField
from product.models import Discount, Product, DownloadableProduct, PriceAdjustmentCalc, PriceAdjustment, Price, get_product_quantity_adjustments
from satchmo_store.contact.models import Contact
from satchmo_utils.fields import CurrencyField
from satchmo_utils.numbers import trunc_decimal
from shipping.fields import ShippingChoiceCharField
from tax.utils import get_tax_processor
import datetime
import keyedcache
import logging
import operator
import signals
import tax

log = logging.getLogger('satchmo_store.shop.models')

class NullConfig(object):
    """Standin for a real config when we don't have one yet."""

    def __init__(self):
        self.store_name = self.store_description = _("Test Store")
        self.store_email = self.street1 = self.street2 = self.city = self.state = self.postal_code = self.phone = ""
        self.site = self.country = None
        self.in_country_only = True
        self.sales_country = None

    def _options(self):
        return ConfigurationSettings()

    options = property(fget=_options)

    def __str__(self):
        return "Test Store - no configured store exists!"

class ConfigManager(models.Manager):
    def get_current(self, site=None):
        """Convenience method to get the current shop config"""
        if not site:
            site = Site.objects.get_current()

        site = site.id

        try:
            shop_config = keyedcache.cache_get("Config", site)
        except keyedcache.NotCachedError, nce:
            try:
                shop_config = self.get(site__id__exact=site)
                keyedcache.cache_set(nce.key, value=shop_config)
            except Config.DoesNotExist:
                log.warning("No Shop Config found, using test shop config for site=%s.", site)
                shop_config = NullConfig()

        return shop_config

class Config(models.Model):
    """
    Used to store specific information about a store.  Also used to
    configure various store behaviors
    """
    site = models.OneToOneField(Site, verbose_name=_("Site"), primary_key=True)
    store_name = models.CharField(_("Store Name"),max_length=100, unique=True)
    store_description = models.TextField(_("Description"), blank=True, null=True)
    store_email = models.EmailField(_("Email"), blank=True, null=True, max_length=75)
    street1=models.CharField(_("Street"),max_length=50, blank=True, null=True)
    street2=models.CharField(_("Street"), max_length=50, blank=True, null=True)
    city=models.CharField(_("City"), max_length=50, blank=True, null=True)
    state=models.CharField(_("State"), max_length=30, blank=True, null=True)
    postal_code=models.CharField(_("Zip Code"), blank=True, null=True, max_length=9)
    country=models.ForeignKey(Country, blank=True, null=False, verbose_name=_('Country'))
    phone = models.CharField(_("Phone Number"), blank=True, null=True, max_length=30)
    in_country_only = models.BooleanField(_("Only sell to in-country customers?"), default=True)
    sales_country = models.ForeignKey(Country, blank=True, null=True,
                                     related_name='sales_country',
                                     verbose_name=_("Default country for customers"))
    shipping_countries = models.ManyToManyField(Country, blank=True, verbose_name=_("Shipping Countries"), related_name="shop_configs")

    objects = ConfigManager()

    def _options(self):
        return ConfigurationSettings()

    options = property(fget=_options)

    def areas(self):
        """Get country areas (states/counties).  Used in forms."""
        if self.in_country_only:
            return self.sales_country.adminarea_set.filter(active=True)
        else:
            return None

    def countries(self):
        """Get country selections.  Used in forms."""
        if self.in_country_only:
            return Country.objects.filter(pk=self.sales_country.pk)
        else:
            return self.shipping_countries.filter(active=True)


    def _base_url(self, secure=False):
        prefix = "http"
        if secure:
            prefix += "s"
        return prefix + "://" + self.site.domain

    base_url = property(fget=_base_url)

    def save(self, force_insert=False, force_update=False):
        keyedcache.cache_delete("Config", self.site.id)
        # ensure the default country is in shipping countries
        mycountry = self.country

        if mycountry:
            if not self.sales_country:
                log.debug("%s: No sales_country set, adding country of store, '%s'", self, mycountry)
                self.sales_country = mycountry

# This code doesn't work when creating a new site. At the time of creation, all of the necessary relationships
# aren't setup. I modified the load_store code so that it would create this relationship manually when running
# with sample data. This is a bit of a django limitation so I'm leaving this in here for now. - CBM
#            salescountry = self.sales_country
#            try:
#                need = self.shipping_countries.get(pk=salescountry.pk)
#            except Country.DoesNotExist:
#                log.debug("%s: Adding default country '%s' to shipping countries", self, salescountry.iso2_code)
#                self.shipping_countries.add(salescountry)
        else:
            log.warn("%s: has no country set", self)

        super(Config, self).save(force_insert=force_insert, force_update=force_update)
        keyedcache.cache_set("Config", self.site.id, value=self)

    def __unicode__(self):
        return self.store_name

    class Meta:
        verbose_name = _("Store Configuration")
        verbose_name_plural = _("Store Configurations")


class NullCart(object):
    """Standin for a real cart when we don't have one yet.  More convenient than testing for null all the time."""
    desc = None
    date_time_created = None
    customer = None
    total = Decimal("0")
    numItems = 0

    def add_item(self, *args, **kwargs):
        pass

    def remove_item(self, *args, **kwargs):
        pass

    def empty(self):
        pass

    def __str__(self):
        return "NullCart (empty)"

    def __iter__(self):
        return iter([])

    def __len__(self):
        return 0

class OrderCart(NullCart):
    """Allows us to fake a cart if we are reloading an order."""

    def __init__(self, order):
        self._order = order

    def _numItems(self):
        return self._order.orderitem_set.count()

    numItems = property(_numItems)

    def _cartitem_set(self):
        return self._order.orderitem_set

    cartitem_set = property(_cartitem_set)

    def _total(self):
        return self._order.balance

    total = property(_total)

    is_shippable = False

    def __str__(self):
        return "OrderCart (%i) = %i" % (self._order.id, len(self))

    def __len__(self):
        return self.numItems

class CartManager(models.Manager):

    def from_request(self, request, create=False, return_nullcart=True):
        """Get the current cart from the request"""
        cart = None
        try:
            contact = Contact.objects.from_request(request, create=False)
        except Contact.DoesNotExist:
            contact = None

        if 'cart' in request.session:
            cartid = request.session['cart']
            if cartid == "order":
                log.debug("Getting Order Cart from request")
                try:
                    order = Order.objects.from_request(request)
                    cart = OrderCart(order)
                except Order.DoesNotExist:
                    pass

            else:
                try:
                    cart = Cart.objects.get(id=cartid)
                except Cart.DoesNotExist:
                    log.debug('Removing invalid cart from session')
                    del request.session['cart']

        if isinstance(cart, NullCart) and not isinstance(cart, OrderCart) and contact is not None:
            carts = Cart.objects.filter(customer=contact)
            if carts.count() > 0:
                cart = carts[0]
                request.session['cart'] = cart.id

        if not cart:
            if create:
                site = Site.objects.get_current()
                if contact is None:
                    cart = Cart(site=site)
                else:
                    cart = Cart(site=site, customer=contact)
                cart.save()
                request.session['cart'] = cart.id

            elif return_nullcart:
                cart = NullCart()

            else:
                raise Cart.DoesNotExist()

        #log.debug("Cart: %s", cart)
        return cart


class Cart(models.Model):
    """
    Store items currently in a cart
    The desc isn't used but it is needed to make the admin interface work appropriately
    Could be used for debugging
    """
    site = models.ForeignKey(Site, verbose_name=_('Site'))
    desc = models.CharField(_("Description"), blank=True, null=True, max_length=10)
    date_time_created = models.DateTimeField(_("Creation Date"))
    customer = models.ForeignKey(Contact, blank=True, null=True, verbose_name=_('Customer'))

    objects = CartManager()

    def _get_count(self):
        itemCount = 0
        for item in self.cartitem_set.all():
            itemCount += item.quantity
        return (itemCount)
    numItems = property(_get_count)

    def _get_discount(self):
        return self.undiscounted_total - self.total

    discount = property(_get_discount)

    def _get_total(self, include_discount=True):
        total = Decimal("0")
        for item in self.cartitem_set.all():
            if include_discount:
                total += item.line_total
            else:
                total += item.undiscounted_line_total
        return(total)
    total = property(_get_total)

    def _get_undiscounted_total(self):
        return self._get_total(False)

    undiscounted_total = property(_get_undiscounted_total)

    def __iter__(self):
        return iter(self.cartitem_set.all())

    def __len__(self):
        return self.cartitem_set.count()

    def __unicode__(self):
        return u"Shopping Cart (%s)" % self.date_time_created

    def add_item(self, chosen_item, number_added, details={}):
        alreadyInCart = False
        # Custom Products will not be added, they will each get their own line item
        if 'CustomProduct' in chosen_item.get_subtypes():
            item_to_modify = CartItem(cart=self, product=chosen_item, quantity=Decimal('0'))
        else:
            item_to_modify = CartItem(cart=self, product=chosen_item, quantity=Decimal('0'))
            for similarItem in self.cartitem_set.filter(product__id = chosen_item.id):
                looksTheSame = len(details) == similarItem.details.count()
                if looksTheSame:
                    for detail in details:
                        try:
                            similarItem.details.get(
                                    name=detail['name'],
                                    value=detail['value'],
                                    price_change=detail['price_change']
                                    )
                        except CartItemDetails.DoesNotExist:
                            looksTheSame = False
                if looksTheSame:
                    item_to_modify = similarItem
                    alreadyInCart = True
                    break

        # Verify that the 'item_to_modify' can be added to the cart regardless
        # of whether or not it is already in the cart
        signals.satchmo_cart_add_verify.send(self, cart=self, cartitem=item_to_modify, added_quantity=number_added, details=details)
        if not alreadyInCart:
            self.cartitem_set.add(item_to_modify)

        item_to_modify.quantity += number_added
        item_to_modify.save()
        if not alreadyInCart:
            for data in details:
                item_to_modify.add_detail(data)

        return item_to_modify

    def remove_item(self, chosen_item_id, number_removed):
        item_to_modify = self.cartitem_set.get(id = chosen_item_id)
        item_to_modify.quantity -= number_removed
        if item_to_modify.quantity <= 0:
            item_to_modify.delete()
        self.save()

    def empty(self):
        for item in self.cartitem_set.all():
            item.delete()
        self.save()

    def save(self, force_insert=False, force_update=False):
        """Ensure we have a date_time_created before saving the first time."""
        if not self.pk:
            self.date_time_created = datetime.datetime.now()
        try:
            site = self.site
        except Site.DoesNotExist:
            self.site = Site.objects.get_current()
        super(Cart, self).save(force_insert=force_insert, force_update=force_update)

    def _get_shippable(self):
        """Return whether the cart contains shippable items."""
        for cartitem in self.cartitem_set.all():
            if cartitem.is_shippable:
                return True
        return False
    is_shippable = property(_get_shippable)

    def get_shipment_list(self):
        """Return a list of shippable products, where each item is split into
        multiple elements, one for each quantity."""
        items = []
        for cartitem in self.cartitem_set.all():
            if cartitem.is_shippable:
                p = cartitem.product
                q =  int(cartitem.quantity.quantize(Decimal('0'), ROUND_CEILING))
                for single in range(0, q):
                    items.append(p)
        return items

    class Meta:
        verbose_name = _("Shopping Cart")
        verbose_name_plural = _("Shopping Carts")

class NullCartItem(object):
    def __init__(self, itemid):
        self.id = itemid
        self.quantity = Decimal('0')
        self.line_total = 0

class CartItem(models.Model):
    """
    An individual item in the cart
    """
    cart = models.ForeignKey(Cart, verbose_name=_('Cart'))
    product = models.ForeignKey(Product, verbose_name=_('Product'))
    quantity = models.DecimalField(_("Quantity"),  max_digits=18,  decimal_places=6)

    def _get_line_unitprice(self, include_discount=True):
        # Get the qty discount price as the unit price for the line.

        self.qty_price = self.get_qty_price(self.quantity, include_discount=include_discount)
        self.detail_price = self.get_detail_price()
        #send signal to possibly adjust the unitprice
        if include_discount:
            signals.satchmo_cartitem_price_query.send(self, cartitem=self)
        price = self.qty_price + self.detail_price

        #clean up temp vars
        del self.qty_price
        del self.detail_price

        return price

    unit_price = property(_get_line_unitprice)

    def _get_undiscounted_unitprice(self):
        return self._get_line_unitprice(include_discount=False)

    undiscounted_unit_price = property(_get_undiscounted_unitprice)

    def get_detail_price(self):
        """Get the delta price based on detail modifications"""
        delta = Decimal("0")
        if self.has_details:
            for detail in self.details.all():
                if detail.price_change and detail.value:
                    delta += detail.price_change
        return delta

    def get_qty_price(self, qty, include_discount=True):
        """Get the price for for each unit before any detail modifications"""
        return self.product.get_qty_price(qty, include_discount=include_discount)

    def _get_line_total(self):
        return self.unit_price * self.quantity
    line_total = property(_get_line_total)

    def _get_undiscounted_line_total(self):
        return self.undiscounted_unit_price * self.quantity

    undiscounted_line_total = property(_get_undiscounted_line_total)

    def _get_description(self):
        return self.product.translated_name()
    description = property(_get_description)

    def _is_shippable(self):
        return self.product.is_shippable

    is_shippable = property(fget=_is_shippable)

    def add_detail(self, data):
        detl = CartItemDetails(cartitem=self, name=data['name'], value=data['value'], sort_order=data['sort_order'], price_change=data['price_change'])
        detl.save()
        #self.details.add(detl)

    def _has_details(self):
        """
        Determine if this specific item has more detail
        """
        return (self.details.count() > 0)

    has_details = property(_has_details)

    def __unicode__(self):
        currency = config_value('LANGUAGE','CURRENCY')
        currency = currency.replace("_", " ")
        return u'%s - %s %s%s' % (self.quantity, self.product.name,
            force_unicode(currency), self.line_total)

    class Meta:
        verbose_name = _("Cart Item")
        verbose_name_plural = _("Cart Items")
        ordering = ('id',)

class CartItemDetails(models.Model):
    """
    An arbitrary detail about a cart item.
    """
    cartitem = models.ForeignKey(CartItem, related_name='details', )
    value = models.TextField(_('detail'))
    name = models.CharField(_('name'), max_length=100)
    price_change = CurrencyField(_("Item Detail Price Change"), max_digits=6,
        decimal_places=2, blank=True, null=True)
    sort_order = models.IntegerField(_("Sort Order"),
        help_text=_("The display order for this group."))

    class Meta:
        ordering = ('sort_order',)
        verbose_name = _("Cart Item Detail")
        verbose_name_plural = _("Cart Item Details")

from satchmo_store.shop.order_models import *

class OrderItem(models.Model):
    """
    A line item on an order.
    """
    order = models.ForeignKey(Order, verbose_name=_("Order"))
    product = models.ForeignKey(Product, verbose_name=_("Product"))
    quantity = models.DecimalField(_("Quantity"),  max_digits=18,  decimal_places=6)
    unit_price = CurrencyField(_("Unit price"),
        max_digits=18, decimal_places=10)
    unit_tax = CurrencyField(_("Unit tax"), default=Decimal('0.00'),
        max_digits=18, decimal_places=10)
    line_item_price = CurrencyField(_("Line item price"),
        max_digits=18, decimal_places=10)
    tax = CurrencyField(_("Line item tax"), default=Decimal('0.00'),
        max_digits=18, decimal_places=10)
    expire_date = models.DateField(_("Subscription End"), help_text=_("Subscription expiration date."), blank=True, null=True)
    completed = models.BooleanField(_("Completed"), default=False)
    discount = CurrencyField(_("Line item discount"),
        max_digits=18, decimal_places=10, blank=True, null=True)

    def __unicode__(self):
        return self.product.translated_name()

    def _get_category(self):
        return(self.product.get_category.translated_name())
    category = property(_get_category)

    def _is_shippable(self):
        return self.product.is_shippable

    is_shippable = property(fget=_is_shippable)

    def _has_details(self):
        """Determine if this specific item has more detail"""
        return (self.orderitemdetail_set.count() > 0)

    has_details = property(_has_details)

    def get_detail_price(self):
        """Get the delta price based on detail modifications"""
        delta = Decimal("0.000000")
        if self.has_details:
            for detail in self.orderitemdetail_set.all():
                if detail.price_change and detail.value:
                    delta += detail.price_change
        return delta

    def _sub_total(self):
        if self.discount:
            return self.line_item_price-self.discount
        else:
            return self.line_item_price
    sub_total = property(_sub_total)

    def _total_with_tax(self):
        return self.sub_total + self.tax
    total_with_tax = property(_total_with_tax)

    def _unit_price_with_tax(self):
        return self.unit_price + self.unit_tax
    unit_price_with_tax = property(_unit_price_with_tax)

    def _get_description(self):
        return self.product.translated_name()
    description = property(_get_description)

    def _get_line_total(self):
        return self.unit_price * self.quantity
    line_total = property(_get_line_total)

    def save(self, force_insert=False, force_update=False):
        self.update_tax()
        super(OrderItem, self).save(force_insert=force_insert, force_update=force_update)

    def update_tax(self):
        taxclass = self.product.taxClass
        processor = get_tax_processor(order=self.order)

        if self.product.taxable:
            self.unit_tax = processor.by_price(taxclass, self.unit_price)
            self.tax = processor.by_orderitem(self)

    class Meta:
        verbose_name = _("Order Line Item")
        verbose_name_plural = _("Order Line Items")
        ordering = ('id',)

class OrderItemDetail(models.Model):
    """
    Name, value pair and price delta associated with a specific item in an order
    """
    item = models.ForeignKey(OrderItem, verbose_name=_("Order Item"), )
    name = models.CharField(_('Name'), max_length=100)
    value = models.CharField(_('Value'), max_length=255)
    price_change = CurrencyField(_("Price Change"), max_digits=18, decimal_places=10, blank=True, null=True)
    sort_order = models.IntegerField(_("Sort Order"),
        help_text=_("The display order for this group."))

    def __unicode__(self):
        return u"%s - %s,%s" % (self.item, self.name, self.value)

    class Meta:
        verbose_name = _("Order Item Detail")
        verbose_name_plural = _("Order Item Details")
        ordering = ('sort_order',)

class DownloadLink(models.Model):
    downloadable_product = models.ForeignKey(DownloadableProduct, verbose_name=_('Downloadable product'))
    order = models.ForeignKey(Order, verbose_name=_('Order'))
    key = models.CharField(_('Key'), max_length=40)
    num_attempts = models.IntegerField(_('Number of attempts'), )
    time_stamp = models.DateTimeField(_('Time stamp'), )
    active = models.BooleanField(_('Active'), default=True)

    def _attempts_left(self):
        return self.downloadable_product.num_allowed_downloads - self.num_attempts
    attempts_left = property(_attempts_left)

    def is_valid(self):
        # Check num attempts and expire_minutes
        if not self.downloadable_product.active:
            return (False, _("This download is no longer active"))
        if self.num_attempts >= self.downloadable_product.num_allowed_downloads:
            return (False, _("You have exceeded the number of allowed downloads."))
        expire_time = datetime.timedelta(minutes=self.downloadable_product.expire_minutes) + self.time_stamp
        if datetime.datetime.now() > expire_time:
            return (False, _("This download link has expired."))
        return (True, "")

    def get_absolute_url(self):
        return('satchmo_store.shop.views.download.process', (), { 'download_key': self.key})
    get_absolute_url = models.permalink(get_absolute_url)

    def get_full_url(self):
        url = urlresolvers.reverse('satchmo_download_process', kwargs= {'download_key': self.key})
        return('http://%s%s' % (Site.objects.get_current(), url))

    def save(self, force_insert=False, force_update=False):
        """
       Set the initial time stamp
        """
        if self.time_stamp is None:
            self.time_stamp = datetime.datetime.now()
        super(DownloadLink, self).save(force_insert=force_insert, force_update=force_update)

    def __unicode__(self):
        return u"%s - %s" % (self.downloadable_product.product.slug, self.time_stamp)

    def _product_name(self):
        return u"%s" % (self.downloadable_product.product.translated_name())
    product_name=property(_product_name)

    class Meta:
        verbose_name = _("Download Link")
        verbose_name_plural = _("Download Links")

class OrderStatus(models.Model):
    """
    An order will have multiple statuses as it moves its way through processing.
    """
    order = models.ForeignKey(Order, verbose_name=_("Order"))
    status = models.CharField(_("Status"),
        max_length=20, choices=ORDER_STATUS, blank=True)
    notes = models.CharField(_("Notes"), max_length=100, blank=True)
    time_stamp = models.DateTimeField(_("Timestamp"))

    def __unicode__(self):
        return self.status

    def save(self, force_insert=False, force_update=False):
        if not self.pk and not self.time_stamp:
            self.time_stamp = datetime.datetime.now()
        super(OrderStatus, self).save(force_insert=force_insert, force_update=force_update)
        self.order.update_status(self.status)

    class Meta:
        verbose_name = _("Order Status")
        verbose_name_plural = _("Order Statuses")
        ordering = ('time_stamp',)
        get_latest_by = 'time_stamp'

class OrderPaymentBase(models.Model):
    payment = PaymentChoiceCharField(_("Payment Method"),
        max_length=25, blank=True)
    amount = CurrencyField(_("amount"),
        max_digits=18, decimal_places=10, blank=True, null=True)
    time_stamp = models.DateTimeField(_("timestamp"), blank=True, null=True)
    transaction_id = models.CharField(_("Transaction ID"), max_length=45, blank=True, null=True)
    details = models.CharField(_("Details"), max_length=255, blank=True, null=True)
    reason_code = models.CharField(_('Reason Code'),  max_length=255, blank=True, null=True)

    def _credit_card(self):
        """Return the credit card associated with this payment."""
        try:
            return self.creditcards.get()
        except self.creditcards.model.DoesNotExist:
            return None
    credit_card = property(_credit_card)

    def _amount_total(self):
        return moneyfmt(self.amount)

    amount_total = property(fget=_amount_total)

    def save(self, force_insert=False, force_update=False):
        if not self.pk:
            self.time_stamp = datetime.datetime.now()

        super(OrderPaymentBase, self).save(force_insert=force_insert, force_update=force_update)

    class Meta:
        abstract = True

class OrderAuthorization(OrderPaymentBase):
    order = models.ForeignKey(Order, related_name="authorizations")
    capture = models.ForeignKey('OrderPayment', related_name="authorizations")
    complete = models.BooleanField(_('Complete'), default=False)

    def __unicode__(self):
        if self.id is not None:
            return u"Order Authorization #%i" % self.id
        else:
            return u"Order Authorization (unsaved)"

    def remaining(self):
        payments = [p.amount for p in self.order.payments.all()]
        if payments:
            amount = reduce(operator.add, payments)
        else:
            amount = Decimal('0.00')

        remaining = self.order.total - amount
        if remaining > self.amount:
            remaining = self.amount

        return trunc_decimal(remaining, 2)

    def save(self, force_insert=False, force_update=False):
        # create linked payment
        try:
            capture = self.capture
        except OrderPayment.DoesNotExist:
            log.debug('Payment Authorization - creating linked payment')
            log.debug('order is: %s', self.order)
            self.capture = OrderPayment.objects.create_linked(self)
        super(OrderPaymentBase, self).save(force_insert=force_insert, force_update=force_update)

    class Meta:
        verbose_name = _("Order Payment Authorization")
        verbose_name_plural = _("Order Payment Authorizations")

class OrderPaymentManager(models.Manager):
    def create_linked(self, other):
        linked = OrderPayment(
                order = other.order,
                payment = other.payment,
                amount=Decimal('0.00'),
                transaction_id="LINKED",
                details=other.details,
                reason_code="")
        linked.save()
        return linked

class OrderPayment(OrderPaymentBase):
    order = models.ForeignKey(Order, related_name="payments")

    objects = OrderPaymentManager()

    def __unicode__(self):
        if self.id is not None:
            return u"Order Payment #%i" % self.id
        else:
            return u"Order Payment (unsaved)"

    class Meta:
        verbose_name = _("Order Payment")
        verbose_name_plural = _("Order Payments")

class OrderPendingPayment(OrderPaymentBase):
    order = models.ForeignKey(Order, related_name="pendingpayments")
    capture = models.ForeignKey('OrderPayment', related_name="pendingpayments")

    def __unicode__(self):
        if self.id is not None:
            return u"Order Pending Payment #%i" % self.id
        else:
            return u"Order Pending Payment (unsaved)"

    def save(self, force_insert=False, force_update=False):
        # create linked payment
        try:
            capture = self.capture
        except OrderPayment.DoesNotExist:
            log.debug('Pending Payment - creating linked payment')
            self.capture = OrderPayment.objects.create_linked(self)
        super(OrderPaymentBase, self).save(force_insert=force_insert, force_update=force_update)

    class Meta:
        verbose_name = _("Order Pending Payment")
        verbose_name_plural = _("Order Pending Payments")

class OrderPaymentFailure(OrderPaymentBase):
    order = models.ForeignKey(Order, null=True, blank=True, related_name='paymentfailures')

class OrderVariable(models.Model):
    order = models.ForeignKey(Order, related_name="variables")
    key = models.SlugField(_('key'), )
    value = models.CharField(_('value'), max_length=100)

    class Meta:
        ordering=('key',)
        verbose_name = _("Order variable")
        verbose_name_plural = _("Order variables")

    def __unicode__(self):
        if len(self.value)>10:
            v = self.value[:10] + '...'
        else:
            v = self.value
        return u"OrderVariable: %s=%s" % (self.key, v)

class OrderTaxDetail(models.Model):
    """A tax line item"""
    order = models.ForeignKey(Order, related_name="taxes")
    method = models.CharField(_("Model"), max_length=50, )
    description = models.CharField(_("Description"), max_length=50, blank=True)
    tax = CurrencyField(_("Tax"),
        max_digits=18, decimal_places=10, blank=True, null=True)

    def __unicode__(self):
        if self.description:
            return u"Tax: %s %s" % (self.description, self.tax)
        else:
            return u"Tax: %s" % self.tax

    class Meta:
        verbose_name = _('Order tax detail')
        verbose_name_plural = _('Order tax details')
        ordering = ('id',)

import config

import listeners
listeners.start_default_listening()
