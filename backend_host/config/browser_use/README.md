Browser use does not natively detect all flutter elements
we need to overwrite its index.js with our customize buildDomTree.js located in your package inside your venv 
pip show browser-use to locate it then 
cd /virtualpytest/venv/lib/python3.11/site-packages/browser_use/dom/dom_tree
cp index.js index_bak.js


