from django.contrib.sites.models import Site
from django.db import models
from django.utils.translation import ugettext_lazy as _

from satchmo_store.contact.models import Contact
from satchmo_utils.fields import CurrencyField
from shipping.fields import ShippingChoiceCharField

ORDER_CHOICES = (
    ('Online', _('Online')),
    ('In Person', _('In Person')),
    ('Show', _('Show')),
)

ORDER_STATUS = (
    ('Temp', _('Temp')),
    ('New', _('New')),
    ('Blocked', _('Blocked')),
    ('In Process', _('In Process')),
    ('Billed', _('Billed')),
    ('Shipped', _('Shipped')),
    ('Complete', _('Complete')),
    ('Cancelled', _('Cancelled')),
)

class OrderManager(models.Manager):
    def from_request(self, request):
        """Get the order from the session

        Returns:
        - Order object
        """
        order = None
        if 'orderID' in request.session:
            try:
                order = Order.objects.get(id=request.session['orderID'])
                # TODO: Validate against logged-in user.
            except Order.DoesNotExist:
                pass

            if not order:
                del request.session['orderID']

        if not order:
            raise Order.DoesNotExist()

        return order

    def remove_partial_order(self, request):
        """Delete cart from request if it exists and is incomplete (has no status)"""
        try:
            order = Order.objects.from_request(request)
            if not order.status:
                del request.session['orderID']
                log.info("Deleting incomplete order #%i from database", order.id)
                order.delete()
                return True
        except Order.DoesNotExist:
            pass
        return False

class Order(models.Model):
    """
    Orders contain a copy of all the information at the time the order was
    placed.
    """
    site = models.ForeignKey(Site, verbose_name=_('Site'))
    contact = models.ForeignKey(Contact, verbose_name=_('Contact'))
    ship_addressee = models.CharField(_("Addressee"), max_length=61, blank=True)
    ship_street1 = models.CharField(_("Street"), max_length=80, blank=True)
    ship_street2 = models.CharField(_("Street"), max_length=80, blank=True)
    ship_city = models.CharField(_("City"), max_length=50, blank=True)
    ship_state = models.CharField(_("State"), max_length=50, blank=True)
    ship_postal_code = models.CharField(_("Zip Code"), max_length=30, blank=True)
    ship_country = models.CharField(_("Country"), max_length=2, blank=True)
    bill_addressee = models.CharField(_("Addressee"), max_length=61, blank=True)
    bill_street1 = models.CharField(_("Street"), max_length=80, blank=True)
    bill_street2 = models.CharField(_("Street"), max_length=80, blank=True)
    bill_city = models.CharField(_("City"), max_length=50, blank=True)
    bill_state = models.CharField(_("State"), max_length=50, blank=True)
    bill_postal_code = models.CharField(_("Zip Code"), max_length=30, blank=True)
    bill_country = models.CharField(_("Country"), max_length=2, blank=True)
    notes = models.TextField(_("Notes"), blank=True, null=True)
    sub_total = CurrencyField(_("Subtotal"),
        max_digits=18, decimal_places=10, blank=True, null=True, display_decimal=4)
    total = CurrencyField(_("Total"),
        max_digits=18, decimal_places=10, blank=True, null=True, display_decimal=4)
    discount_code = models.CharField(_("Discount Code"), max_length=20, blank=True, null=True,
        help_text=_("Coupon Code"))
    discount = CurrencyField(_("Discount amount"),
        max_digits=18, decimal_places=10, blank=True, null=True)
    method = models.CharField(_("Order method"),
        choices=ORDER_CHOICES, max_length=50, blank=True)
    shipping_description = models.CharField(_("Shipping Description"),
        max_length=50, blank=True, null=True)
    shipping_method = models.CharField(_("Shipping Method"),
        max_length=50, blank=True, null=True)
    shipping_model = ShippingChoiceCharField(_("Shipping Models"),
        max_length=30, blank=True, null=True)
    shipping_cost = CurrencyField(_("Shipping Cost"),
        max_digits=18, decimal_places=10, blank=True, null=True)
    shipping_discount = CurrencyField(_("Shipping Discount"),
        max_digits=18, decimal_places=10, blank=True, null=True)
    tax = CurrencyField(_("Tax"),
        max_digits=18, decimal_places=10, blank=True, null=True)
    time_stamp = models.DateTimeField(_("Timestamp"), blank=True, null=True)
    status = models.CharField(_("Status"), max_length=20, choices=ORDER_STATUS,
        blank=True, help_text=_("This is set automatically."))

    objects = OrderManager()

    def __unicode__(self):
        return "Order #%s: %s" % (self.id, self.contact.full_name)

    def add_status(self, status=None, notes=""):
        orderstatus = OrderStatus()
        if not status:
            try:
                curr_status = self.orderstatus_set.latest()
                status = curr_status.status
            except OrderStatus.DoesNotExist:
                status = 'New'

        orderstatus.status = status
        orderstatus.notes = notes
        orderstatus.order = self
        orderstatus.save()

    def add_variable(self, key, value):
        """Add an OrderVariable, used for misc stuff that is just too small to get its own field"""
        try:
            v = self.variables.get(key__exact=key)
            v.value = value
        except OrderVariable.DoesNotExist:
            v = OrderVariable(order=self, key=key, value=value)
        v.save()

    def _authorized_remaining(self):
        auths = [p.amount for p in self.authorizations.filter(complete=False)]
        if auths:
            amount = reduce(operator.add, auths)
        else:
            amount = Decimal('0.00')

        return amount

    authorized_remaining = property(fget=_authorized_remaining)

    def get_variable(self, key, default=None):
        qry = self.variables.filter(key__exact=key)
        ct = qry.count()
        if ct == 0:
            return default
        else:
            return qry[0]

    def copy_addresses(self):
        """
        Copy the addresses so we know what the information was at time of order.
        """
        shipaddress = self.contact.shipping_address
        billaddress = self.contact.billing_address
        self.ship_addressee = shipaddress.addressee
        self.ship_street1 = shipaddress.street1
        self.ship_street2 = shipaddress.street2
        self.ship_city = shipaddress.city
        self.ship_state = shipaddress.state
        self.ship_postal_code = shipaddress.postal_code
        self.ship_country = shipaddress.country.iso2_code
        self.bill_addressee = billaddress.addressee
        self.bill_street1 = billaddress.street1
        self.bill_street2 = billaddress.street2
        self.bill_city = billaddress.city
        self.bill_state = billaddress.state
        self.bill_postal_code = billaddress.postal_code
        self.bill_country = billaddress.country.iso2_code

    def remove_all_items(self):
        """Delete all items belonging to this order."""
        for item in self.orderitem_set.all():
            item.delete()
        self.save()

    def _balance(self):
        if self.total is None:
            self.force_recalculate_total(save=True)
        return trunc_decimal(self.total-self.balance_paid, 2)

    balance = property(fget=_balance)

    def balance_forward(self):
        return moneyfmt(self.balance)

    balance_forward = property(fget=balance_forward)

    def _balance_paid(self):
        payments = [p.amount for p in self.payments.all()]
        if payments:
            paid = reduce(operator.add, payments)
        else:
            paid = Decimal("0.0000000000")

        return paid + self.authorized_remaining

    balance_paid = property(_balance_paid)

    def _credit_card(self):
        """Return the credit card associated with this payment."""
        for payment in self.payments.order_by('-time_stamp'):
            try:
                if payment.creditcards.count() > 0:
                    return payment.creditcards.get()
            except ObjectDoesNotExist:
                pass
        return None
    credit_card = property(_credit_card)

    def _full_bill_street(self, delim="\n"):
        """
        Return both billing street entries separated by delim.
        Note - Use linebreaksbr filter to convert to html in templates.
        """
        if self.bill_street2:
            address = self.bill_street1 + delim + self.bill_street2
        else:
            address = self.bill_street1
        return mark_safe(address)
    full_bill_street = property(_full_bill_street)

    def _full_ship_street(self, delim="\n"):
        """
        Return both shipping street entries separated by delim.
        Note - Use linebreaksbr filterto convert to html in templates.
        """
        if self.ship_street2:
            address = self.ship_street1 + delim + self.ship_street2
        else:
            address = self.ship_street1
        return mark_safe(address)
    full_ship_street = property(_full_ship_street)

    def _ship_country_name(self):
        return Country.objects.get(iso2_code=self.ship_country).name
    ship_country_name = property(_ship_country_name)

    def _bill_country_name(self):
        return Country.objects.get(iso2_code=self.bill_country).name
    bill_country_name = property(_bill_country_name)

    def _discounted_sub_total(self):
        return self.sub_total - self.item_discount

    discounted_sub_total = property(_discounted_sub_total)

    def _get_balance_remaining_url(self):
        return ('satchmo_balance_remaining_order', None, {'order_id' : self.id})
    get_balance_remaining_url = models.permalink(_get_balance_remaining_url)

    def _partially_paid(self):
        return self.balance_paid > Decimal("0.0000000000")

    partially_paid = property(_partially_paid)

    def _is_partially_paid(self):
        if self.total:
            return (
                float(self.balance) > 0.0
                and float(self.balance_paid) > 0.0
                and self.balance != self.balance_paid
                )
        else:
            return False

    is_partially_paid = property(fget=_is_partially_paid)

    def payments_completed(self):
        q = self.payments.exclude(transaction_id__isnull = False, transaction_id = "PENDING")
        result = [p for p in q if p.amount]
        return result

    def save(self, force_insert=False, force_update=False):
        """
        Copy addresses from contact. If the order has just been created, set
        the create_date.
        """
        if not self.pk:
            self.time_stamp = datetime.datetime.now()
            self.copy_addresses()
        super(Order, self).save(force_insert=force_insert, force_update=force_update) # Call the "real" save() method.

    def invoice(self):
        url = urlresolvers.reverse('satchmo_print_shipping', None, None, {'doc' : 'invoice', 'id' : self.id})
        return mark_safe(u'<a href="%s">%s</a>' % (url, ugettext('View')))
    invoice.allow_tags = True

    def _item_discount(self):
        """Get the discount of just the items, less the shipping discount."""
        return self.discount-self.shipping_discount
    item_discount = property(_item_discount)

    def packingslip(self):
        url = urlresolvers.reverse('satchmo_print_shipping', None, None, {'doc' : 'packingslip', 'id' : self.id})
        return mark_safe(u'<a href="%s">%s</a>' % (url, ugettext('View')))
    packingslip.allow_tags = True

    def recalculate_total(self, save=True):
        """Calculates sub_total, taxes and total if the order is not already partially paid."""
        if self.is_partially_paid:
            log.debug("Order %i - skipping recalculate_total since product is partially paid.", self.id)
        else:
            self.force_recalculate_total(save=save)

    def force_recalculate_total(self, save=True):
        """Calculates sub_total, taxes and total."""
        zero = Decimal("0.0000000000")
        total_discount = Decimal("0.0000000000")

        discount = Discount.objects.by_code(self.discount_code)
        discount.calc(self)

        discounts = discount.item_discounts
        itemprices = []
        fullprices = []
        for lineitem in self.orderitem_set.all():
            lid = lineitem.id
            if lid in discounts:
                lineitem.discount = discounts[lid]
                total_discount += lineitem.discount
                #log.debug('total_discount (calc): %s', total_discount)
            else:
                lineitem.discount = zero
            # now double check against other discounts, such as tiered discounts
            adjustment = get_product_quantity_adjustments(lineitem.product, qty=lineitem.quantity)
            if adjustment and adjustment.price:
                baseprice = adjustment.price.price
                finalprice = adjustment.final_price()
                #We need to add in any OrderItemDetail price adjustments before we do anything else
                baseprice += lineitem.get_detail_price()
                finalprice += lineitem.get_detail_price()
                if baseprice > finalprice or baseprice != lineitem.unit_price:
                    unitdiscount = (lineitem.discount/lineitem.quantity) + baseprice-finalprice
                    unitdiscount = trunc_decimal(unitdiscount, 2)
                    linediscount = unitdiscount * lineitem.quantity
                    total_discount += linediscount
                    #log.debug('total_discount (line): %s', total_discount)
                    fullydiscounted = (baseprice - unitdiscount) * lineitem.quantity
                    lineitem.unit_price = baseprice
                    lineitem.discount = linediscount
                    lineitem.line_item_price = baseprice * lineitem.quantity
                    log.debug('Adjusting lineitem unit price for %s. Full price=%s, discount=%s.  Final price for qty %d is %s',
                        lineitem.product.slug, baseprice, unitdiscount, lineitem.quantity, fullydiscounted)
            if save:
                lineitem.save()

            itemprices.append(lineitem.sub_total)
            fullprices.append(lineitem.line_item_price)

        shipprice = Price()
        shipprice.price = self.shipping_cost
        shipadjust = PriceAdjustmentCalc(shipprice)
        if 'Shipping' in discounts:
            shipadjust += PriceAdjustment('discount', _('Discount'), discounts['Shipping'])

        signals.satchmo_shipping_price_query.send(self, adjustment=shipadjust)
        shipdiscount = shipadjust.total_adjustment()
        self.shipping_discount = shipdiscount
        total_discount += shipdiscount
        #log.debug('total_discount (+ship): %s', total_discount)

        self.discount = total_discount

        if itemprices:
            item_sub_total = reduce(operator.add, itemprices)
        else:
            item_sub_total = zero

        if fullprices:
            full_sub_total = reduce(operator.add, fullprices)
        else:
            full_sub_total = zero

        self.sub_total = full_sub_total

        taxProcessor = get_tax_processor(self)
        totaltax, taxrates = taxProcessor.process()
        self.tax = totaltax

        # clear old taxes
        for taxdetl in self.taxes.all():
            taxdetl.delete()

        for taxdesc, taxamt in taxrates.items():
            taxdetl = OrderTaxDetail(order=self, tax=taxamt, description=taxdesc, method=taxProcessor.method)
            taxdetl.save()

        log.debug("Order #%i, recalc: sub_total=%s, shipping=%s, discount=%s, tax=%s",
            self.id,
            moneyfmt(item_sub_total),
            moneyfmt(self.shipping_sub_total),
            moneyfmt(self.discount),
            moneyfmt(self.tax))

        self.total = Decimal(item_sub_total + self.shipping_sub_total + self.tax)

        if save:
            self.save()

    def shippinglabel(self):
        url = urlresolvers.reverse('satchmo_print_shipping', None, None, {'doc' : 'shippinglabel', 'id' : self.id})
        return mark_safe(u'<a href="%s">%s</a>' % (url, ugettext('View')))
    shippinglabel.allow_tags = True

    def _order_total(self):
        #Needed for the admin list display
        return moneyfmt(self.total)
    order_total = property(_order_total)

    def order_success(self):
        """Run each item's order_success method."""
        log.info("Order success: %s", self)
        for orderitem in self.orderitem_set.all():
            subtype = orderitem.product.get_subtype_with_attr('order_success')
            if subtype:
                subtype.order_success(self, orderitem)

        signals.order_success.send(self, order=self)

    def order_cancel(self):
        """Ask if the order can be cancelled. By default, do not cancel shipped, completed and
        already cancelled orders."""
        self.is_cancellable = self.status not in ('Shipped', 'Completed', 'Cancelled')
        # listeners can override default flag setting and (dis)allow cancellation
        signals.order_cancel_query.send(self, order=self)
        if self.is_cancellable:
           self.add_status('Cancelled')
           signals.order_cancelled.send(self, order=self)
        return self.is_cancellable

    def _paid_in_full(self):
        """True if total has been paid"""
        return self.balance == Decimal('0.00')
    paid_in_full = property(fget=_paid_in_full)

    def _has_downloads(self):
        """Determine if there are any downloadable products on this order"""
        if self.downloadlink_set.count() > 0:
            return True
        return False
    has_downloads = property(_has_downloads)

    def _is_downloadable(self):
        """Determine if all products on this order are downloadable"""
        for orderitem in self.orderitem_set.all():
           if not orderitem.product.is_downloadable:
               return False
        return True
    is_downloadable = property(_is_downloadable)

    def _is_shippable(self):
        """Determine if we will be shipping any items on this order """
        for orderitem in self.orderitem_set.all():
            if orderitem.is_shippable:
                return True
        return False
    is_shippable = property(_is_shippable)

    def _shipping_sub_total(self):
        if self.shipping_cost is None:
            self.shipping_cost = Decimal('0.00')
        if self.shipping_discount is None:
            self.shipping_discount = Decimal('0.00')
        return self.shipping_cost-self.shipping_discount
    shipping_sub_total = property(_shipping_sub_total)

    def _shipping_tax(self):
        rates = self.taxes.filter(description__iexact = 'shipping')
        if rates.count()>0:
            tax = reduce(operator.add, [t.tax for t in rates])
        else:
            tax = Decimal("0.0000000000")
        return tax
    shipping_tax = property(_shipping_tax)

    def _shipping_with_tax(self):
        return self.shipping_sub_total + self.shipping_tax
    shipping_with_tax = property(_shipping_with_tax)

    def sub_total_with_tax(self):
        return reduce(operator.add, [o.total_with_tax for o in self.orderitem_set.all()])

    def update_status(self, status):
        """WARNING: To just change order status, use Order.add_status().
        This method is called back when OrderStatus is saved and does not create required object."""
        oldstatus = self.status
        self.status = status
        self.save()
        if (oldstatus != self.status):
            signals.satchmo_order_status_changed.send(self, oldstatus=oldstatus, newstatus=status, order=self)

    def validate(self, request):
        """
        Return whether the order is valid.
        Not guaranteed to be side-effect free.
        """
        valid = True
        for orderitem in self.orderitem_set.all():
            for subtype_name in orderitem.product.get_subtypes():
                subtype = getattr(orderitem.product, subtype_name.lower())
                validate_method = getattr(subtype, 'validate_order', None)
                if validate_method:
                    valid = valid and validate_method(request, self, orderitem)
        return valid

    class Meta:
        verbose_name = _("Product Order")
        verbose_name_plural = _("Product Orders")
