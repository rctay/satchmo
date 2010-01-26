from shipping.modules.tieredweight.models import Carrier, Shipper, Zone
from satchmo_utils import load_once

load_once('tiered', 'shipping.modules.tieredweight')

def get_methods():
    #return [Shipper(carrier) for carrier in Carrier.objects.filter(active=True)]
    return [Shipper(zone) for zone in Zone.objects.filter()]