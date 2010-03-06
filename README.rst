Git Mirror for Satchmo
======================
This repository is the unofficial git mirror for the `satchmo project
<http://www.satchmoproject.com/>`_, with some of my own hacks thrown in.

Branch Map
----------
The branch `tip <http://github.com/rctay/satchmo/tree/tip>`_ tracks the `tip
tag <http://bitbucket.org/chris1610/satchmo/src/11463028d624/>`_ in satchmo
hg's repository.

(On everything else, don't count on them to be fast-forwardable or stable.)

The branch `master <http://github.com/rctay/satchmo/tree/master>`_ is rebased
on top of `tip`; right now, it contains the README and nothing else, but this
might change in the future.

From time to time, you may see branches prefixed `rc/`; they are probably new
features/work still in development, or finalized and waiting for upstream
approval (see below). In either case, don't count on them to be around or to be
stable.

Development Flow
----------------

1. Hack.

2. Push out changes in a branch (eg. `rc/topic-name`) to my git repo here.

3. Push out changes to my bitbucket/hg repo (no branch name) via `hg-git
   <http://hg-git.github.com/>`_.

4. Create a new ticket on satchmo's issue tracker at bitbucket.

5. Tag my published branch with the ticket number (eg. `rc/ticket-<num>/v1`) and
   push to here.

6. Wait and see how things go; if it's accepted and merged upstream, and I'm
   satisfied with the feature, I'll delete the branch; if not, the process
   repeats.

Repositories Used
-----------------

1. This one.

2. http://bitbucket.org/rctay/satchmo/

   I push out my changes to here for merging upstream.

3. http://bitbucket.org/chris1610/satchmo/

   The official hg repository for satchmo.
