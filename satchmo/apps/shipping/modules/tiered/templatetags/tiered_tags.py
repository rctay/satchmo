from decimal import Decimal
from django import template
from django.utils.safestring import mark_safe
from l10n.utils import moneyfmt
from shipping.modules.tiered.models import Carrier

register = template.Library()

def tiered_shipping(price, args=''):
    if not args:
        raise template.TemplateSyntaxError('tiered_shipping needs the name of the carrier, as value|tiered_shipping:"carrier"')

    try:
        c = Carrier.objects.get(key=args)
    except Carrier.DoesNotExist:
        raise template.TemplateSyntaxError('tiered_shipping needs the name of a valid carrier, could not find carrier "%s"' % args)
    shipping = c.price(Decimal(price))

    return mark_safe(moneyfmt(shipping))

register.filter(tiered_shipping)

def tiered_price_table(carrier):
    """Creates a table with all shipping tiers"""

    try:
        c = Carrier.objects.get(key=carrier)
    except Carrier.DoesNotExist:
        raise template.TemplateSyntaxError('tiered_price_table needs the name of a valid carrier, could not find carrier "%s"' % carrier)

    rows = ['<table class="tiered_price tiered_price_carrier_%s">' % carrier]
    rows.append('<tr><th>Order Total</th><th>Shipping price</th></tr>')
    ranges = []

    last = None
    for tier in c.tiers.all().order_by('-price'):
        t = {}
        t['price'] = moneyfmt(tier.price)
        t['from'] = moneyfmt(tier.min_total)
        if last:
            t['to'] = moneyfmt(last.min_total)
        else:
            t['to'] = None

        ranges.append(t)
        last = tier

    ranges.reverse()

    for tier in ranges:
        price = {}
        price['price'] = tier['price']
        if tier['to']:
            price['range'] = "%s-%s" % (tier['from'], tier['to'])
        else:
            price['range'] = "%s+" % (tier['from'])

        rows.append('<tr><td>%(range)s</td><td>%(price)s</td></tr>' % price)

    rows.append('</table>')
    return mark_safe('\n'.join(rows))

register.filter(tiered_price_table)
