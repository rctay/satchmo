from django.conf import settings
from django.contrib.sites.models import Site
from django.core import urlresolvers
from django.core.files import File
from django.http import HttpResponse
from django.test import TestCase
from django.test.client import Client
from l10n.models import Country
from livesettings import config_get
from product.models import Product
from product.modules.downloadable.models import DownloadLink, DownloadableProduct
from satchmo_store.contact.models import AddressBook, Contact
from satchmo_store.shop.models import Cart, Order
from shipping.modules.flat.shipper import Shipper as flat
from shipping.modules.per.shipper import Shipper as per

import datetime
from decimal import Decimal
import keyedcache
import os
from shutil import rmtree
from tempfile import mkdtemp

class DownloadableShippingTest(TestCase):

    fixtures = ['l10n-data.yaml','test_shop.yaml']

    def setUp(self):
        self.site = Site.objects.get_current()
        self.product1 = Product.objects.create(slug='p1', name='p1', site=self.site)
        self.cart1 = Cart.objects.create(site=self.site)
        self.cartitem1 = self.cart1.add_item(self.product1, 3)

    def tearDown(self):
        keyedcache.cache_delete()

    def test_downloadable_zero_shipping(self):
        subtype2 = DownloadableProduct.objects.create(product=self.product1)
        self.assertEqual(self.product1.get_subtypes(), ('DownloadableProduct',))

        self.assertFalse(subtype2.is_shippable)
        self.assertFalse(self.product1.is_shippable)
        self.assertFalse(self.cart1.is_shippable)
        self.assertEqual(flat(self.cart1, None).cost(), Decimal("0.00"))
        self.assertEqual(per(self.cart1, None).cost(), Decimal("0.00"))

class DownloadableProductTest(TestCase):
    fixtures = ['l10n-data.yaml', 'products.yaml']

    def setUp(self):
        self.site = Site.objects.get_current()

        # setup a contact
        c, _created = Contact.objects.get_or_create(
            first_name="Jim",
            last_name="Tester",
            email="Jim@JimWorld.com",
        )
        ad, _created = AddressBook.objects.get_or_create(
            contact=c, description="home",
            street1 = "test", state="OR", city="Portland",
            country = Country.objects.get(iso2_code__iexact = 'US'),
            is_default_shipping=True,
            is_default_billing=True,
        )

        # setup a order
        o, _created = Order.objects.get_or_create(contact=c, shipping_cost=Decimal('6.00'), site=self.site)

        # setup a temporary source dir
        self.dir = mkdtemp()
        self.file_name = "dl_file"
        self.file = open(os.path.join(self.dir, self.file_name), "w")
        # setup a temporary protected dir
        self.protected_dir = mkdtemp(dir=os.path.normcase(os.path.normpath(settings.MEDIA_ROOT)))
        config_get('PRODUCT', 'PROTECTED_DIR').update(self.protected_dir)
        # a fake SHA
        self.key = "".join(["12abf" for i in range(8)])

        # setup downloads
        self.product, _created = DownloadableProduct.objects.get_or_create(
            product=Product.objects.get(slug='dj-rocks'),
            file=File(self.file),
            num_allowed_downloads=3,
            expire_minutes=1,
        )
        self.product_link, _created = DownloadLink.objects.get_or_create(
            downloadable_product=self.product,
            order=o, key=self.key, num_attempts=0,
            time_stamp=datetime.datetime.now()
        )

        # setup client
        self.domain = 'satchmoserver'
        self.client = Client(SERVER_NAME=self.domain)

    def tearDown(self):
        self.file.close()
        rmtree(self.dir)
        rmtree(self.protected_dir)

    def test_download_link(self):
        """Test that we are able to download a product."""

        pd_url = urlresolvers.reverse('satchmo_download_send', kwargs= {'download_key': self.key})

        # first, hit the url.
        response = self.client.get(pd_url)
        self.assertEqual(response['Location'],
            'http://%s%s' % (
                self.domain,
                urlresolvers.reverse('satchmo_download_process', kwargs= {'download_key': self.key}),
            )
        )

        # follow the redirect to "process" the key.
        response = self.client.get(response['Location'])
        self.assertEqual(self.client.session.get('download_key', None), self.key)

        # we should have gotten a page that says "click here".
        # hit the pd_url again; we should get a sendfile redirect.
        response = self.client.get(pd_url)

        exp_url = "%s%s/%s" % (settings.MEDIA_URL, self.protected_dir.split(os.path.sep)[-1], self.file_name)

        self.assertEqual(response['X-Accel-Redirect'], exp_url)
        self.assertEqual(response['X-Sendfile'], exp_url)
        self.assertEqual(response['X-LIGHTTPD-send-file'], exp_url)
