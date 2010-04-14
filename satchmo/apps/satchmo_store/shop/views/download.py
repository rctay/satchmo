from django.conf import settings
from django.core import urlresolvers
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render_to_response
from django.template import RequestContext
from django.utils.translation import ugettext_lazy as _
from product.modules.downloadable.models import DownloadLink
from satchmo_store.shop.signals import download_url_for_file
import mimetypes

import os
import os.path
import re
from urlparse import urljoin

SHA1_RE = re.compile('^[a-f0-9]{40}$')

def _validate_key(download_key):
    """
    Helper function to make sure the key is valid and all the other constraints on
    the download are still valid.
    Returns a tuple (False,"Error Message", None) or (True, None, dl_product)
    """
    download_key = download_key.lower()
    if not SHA1_RE.search(download_key):
        error_message = _("The download key is invalid.")
        return (False, error_message, None)
    try:
        dl_product = DownloadLink.objects.get(key=download_key)
    except:
        error_message = _("The download key is invalid.")
        return (False, error_message, None)
    valid, msg = dl_product.is_valid()
    if not valid:
        return (False, msg, None)
    else:
        return (True, None, dl_product)

def process(request, download_key):
    """
    Validate that the key is good, then set a session variable.
    Redirect to the download view.

    We use this two step process so that we can easily display meaningful feedback
    to the user.
    """
    valid, msg, dl_product = _validate_key(download_key)
    if not valid:
        context = RequestContext(request, {'error_message': msg})
        return render_to_response('shop/download.html',
                                  context_instance=context)
    else:
        # The key is valid so let's set the session variable and redirect to the
        # download view
        request.session['download_key'] = download_key
        url = urlresolvers.reverse('satchmo_download_send', kwargs= {'download_key': download_key})
        context = RequestContext(request, {'download_product': dl_product,
                                            'dl_url' : url})
        return render_to_response('shop/download.html', context_instance=context)

def send_file(request, download_key):
    """
    After the appropriate session variable has been set, we commence the download.
    The key is maintained in the url but the session variable is used to control the
    download in order to maintain security.

    For this to work, your server must support the X-Sendfile header
    Lighttpd and Apache should both work with the headers used below.
    For apache, will need mod_xsendfile
    For lighttpd, allow-x-send-file must be enabled

    Also, you must ensure that the directory where the file is stored is protected
    from users.

    In lighttpd.conf:
    $HTTP["url"] =~ "^/static/protected/" {
    url.access-deny = ("")
    }

    In Nginx:
    location /protected/{
             internal;
             root /usr/local/www/website/static;
        }

    """
    if not request.session.get('download_key', False):
        url = urlresolvers.reverse('satchmo_download_process', kwargs = {'download_key': download_key})
        return HttpResponseRedirect(url)
    valid, msg, dl_product = _validate_key(request.session['download_key'])
    if not valid:
        url = urlresolvers.reverse('satchmo_download_process', kwargs = {'download_key': request.session['download_key']})
        return HttpResponseRedirect(url)

    # some temp vars
    file = dl_product.downloadable_product.file
    file_path = dl_product.downloadable_product.file.path
    file_name = os.path.split(file_path)[1]

    # generate the url; we do this instead of relying on file.url, as django
    # doesn't seem to do it correctly.
    norm_root = os.path.normcase(os.path.normpath(settings.MEDIA_ROOT))
    norm_path = os.path.normcase(os.path.normpath(file_path))
    url_part = norm_path.split(norm_root)[1].replace('\\', '/')
    # we don't want urljoin to think this is a "root" url.
    if url_part[0] == '/':
        url_part = url_part[1:]

    # poll listeners
    url_dict = {'url': urljoin(settings.MEDIA_URL, url_part)}
    download_url_for_file.send(None, file=file,
        product=dl_product.downloadable_product,
        url_dict=url_dict,
    )
    file_url = url_dict['url']

    dl_product.num_attempts += 1
    dl_product.save()
    del request.session['download_key']
    response = HttpResponse()
    # For Nginx
    response['X-Accel-Redirect'] = file_url
    # For Apache
    response['X-Sendfile'] = file_url
    # For Lighttpd
    response['X-LIGHTTPD-send-file'] = file_url
    response['Content-Disposition'] = "attachment; filename=%s" % file_name
    response['Content-length'] =  os.path.getsize(file_path)
    contenttype, encoding = mimetypes.guess_type(file_name)
    if contenttype:
        response['Content-type'] = contenttype
    return response
