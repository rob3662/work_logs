# Page indexing and Google Search Console checklist

*(Migrated from `webserver_setup/project_template/page_indexing_fixes_checklist.md`.)*

## Overview
This document summarizes common page indexing issues found in Google Search Console and their fixes. Use this checklist to audit your sites and prevent duplicate content and indexing problems.

---

## Issues Found and Fixed

### 1. **Incorrect URLs in robots.txt**
**Problem:** 
- `robots.txt` listed URLs with underscores (`/addition_quiz`) while actual routes used hyphens (`/addition-quiz`)
- This caused Google to try crawling non-existent URLs, resulting in 404 errors
- Google Search Console showed "Not found (404)" errors

**Fix:**
- Updated `robots.txt` to match actual route URLs exactly
- Ensured all URLs use the correct format (hyphens vs underscores)

**Check for Your Sites:**
- [ ] All URLs in `robots.txt` match your actual routes exactly
- [ ] No typos or outdated URLs in `robots.txt`
- [ ] Sitemap location in `robots.txt` is correct

---

### 2. **Missing Redirects for Old URLs**
**Problem:**
- Old URLs (with underscores) weren't redirecting to new URLs (with hyphens)
- This created dead links that Google tried to crawl
- Users and search engines hitting old URLs got 404 errors

**Fix:**
- Added 301 (permanent) redirects from old URLs to new URLs:
  ```python
  @app.route('/multiplication_quiz')
  def redirect_multiplication_quiz():
      return redirect(url_for('multiplication_quiz'), code=301)
  ```

**Check for Your Sites:**
- [ ] If you've changed URL structures, add 301 redirects from old to new URLs
- [ ] Test old URLs to ensure they redirect properly
- [ ] No broken links from URL migrations

---

### 3. **Outdated Static sitemap.xml**
**Problem:**
- Old static `sitemap.xml` file was outdated and may have been indexed by Google
- Static sitemaps require manual updates when routes change
- Google may have discovered old URLs from the static sitemap

**Fix:**
- Replaced static sitemap with dynamic sitemap that generates URLs on-the-fly
- Dynamic sitemap automatically includes all current public routes
- Backed up old static sitemap (renamed to `sitemap.xml.backup`)

**Check for Your Sites:**
- [ ] If using static sitemap, ensure it's up-to-date
- [ ] Consider switching to dynamic sitemap for automatic updates
- [ ] Verify sitemap includes all public pages (not API endpoints)

---

### 4. **Canonical URL Issues (Duplicate Content)**
**Problem:**
- Canonical tag was using `{{ request.url }}` which includes query parameters
- This caused Google to see the same page as multiple different URLs:
  - `https://yoursite.com/about` (indexed)
  - `https://yoursite.com/about?utm_source=google` (not indexed, duplicate)
  - `https://yoursite.com/about?ref=twitter` (not indexed, duplicate)
- Google Search Console showed "Duplicate, Google chose different canonical than user" errors

**Fix:**
- Created context processor to generate normalized canonical URLs:
  ```python
  @app.context_processor
  def inject_canonical_url():
      """Generate normalized canonical URL for the current page"""
      endpoint = request.endpoint
      if endpoint:
          try:
              canonical = url_for(endpoint, _external=True)
          except:
              canonical = request.url.split('?')[0]
      else:
          canonical = request.url.split('?')[0]
      return dict(canonical_url=canonical)
  ```
- Updated template to use normalized canonical URL:
  ```html
  <link rel="canonical" href="{{ canonical_url }}">
  ```
- Also updated Open Graph `og:url` to match canonical URL

**Check for Your Sites:**
- [ ] Every page has a canonical tag
- [ ] Canonical URLs are clean (no query parameters)
- [ ] Canonical URLs use absolute URLs (`_external=True`)
- [ ] Open Graph `og:url` matches canonical URL

---

## Complete Checklist for Site Audits

### robots.txt Audit
- [ ] All URLs in `robots.txt` match actual routes
- [ ] No typos or outdated URLs
- [ ] Sitemap location is correct
- [ ] Disallow rules are appropriate

### URL Redirects
- [ ] Old URLs redirect to new URLs (301 redirects)
- [ ] No broken links from URL changes
- [ ] Test old URLs to confirm redirects work
- [ ] Redirects use proper HTTP status codes (301 for permanent)

### Sitemap
- [ ] Sitemap is up-to-date (dynamic preferred)
- [ ] All public pages are included
- [ ] No API endpoints or POST-only routes in sitemap
- [ ] Sitemap submitted to Google Search Console
- [ ] Sitemap validates correctly

### Canonical Tags
- [ ] Every page has a canonical tag
- [ ] Canonical URLs are clean (no query parameters)
- [ ] Canonical URLs use absolute URLs
- [ ] Open Graph `og:url` matches canonical URL
- [ ] No conflicting canonical tags

### Common Duplicate URL Causes
- [ ] Trailing slashes handled consistently (`/about` vs `/about/`)
- [ ] HTTP vs HTTPS redirects properly
- [ ] www vs non-www handled consistently
- [ ] Query parameters don't create duplicate content
- [ ] URL case sensitivity handled (if applicable)

### Google Search Console Monitoring
- [ ] Check "Why pages aren't indexed" report regularly
- [ ] Look for patterns:
  - "Page with redirect" → Add redirects
  - "Not found (404)" → Fix broken links
  - "Duplicate, Google chose different canonical" → Fix canonical tags
  - "Crawled - currently not indexed" → May resolve over time
- [ ] Use "Request Indexing" for important pages
- [ ] Monitor indexing trends over time

---

## Quick Test Commands

```bash
# Test if old URLs redirect properly
curl -I https://yoursite.com/old-url

# Check robots.txt
curl https://yoursite.com/robots.txt

# Check sitemap
curl https://yoursite.com/sitemap.xml

# Check canonical tag on a page
curl https://yoursite.com/about | grep -i canonical

# Check for multiple canonical tags (should only be one)
curl https://yoursite.com/about | grep -i "rel=\"canonical\"" | wc -l
```

---

## Implementation Examples

### Dynamic Sitemap (Flask)
```python
@app.route('/sitemap.xml')
def sitemap_xml():
    """Generate dynamic sitemap.xml for all public pages"""
    pages = [
        ('index', 'daily', '1.0'),
        ('about', 'monthly', '0.8'),
        # Add all public routes here
    ]
    
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    
    for endpoint, changefreq, priority in pages:
        try:
            url = url_for(endpoint, _external=True)
            lastmod = datetime.utcnow().date().isoformat()
            
            xml.append('<url>')
            xml.append(f'  <loc>{url}</loc>')
            xml.append(f'  <lastmod>{lastmod}</lastmod>')
            xml.append(f'  <changefreq>{changefreq}</changefreq>')
            xml.append(f'  <priority>{priority}</priority>')
            xml.append('</url>')
        except Exception as e:
            logger.warning(f"Error generating sitemap entry for {endpoint}: {e}")
            continue
    
    xml.append('</urlset>')
    return Response('\n'.join(xml), mimetype='application/xml')
```

### Canonical URL Context Processor (Flask)
```python
@app.context_processor
def inject_canonical_url():
    """Generate normalized canonical URL for the current page"""
    endpoint = request.endpoint
    if endpoint:
        try:
            canonical = url_for(endpoint, _external=True)
        except:
            canonical = request.url.split('?')[0]
    else:
        canonical = request.url.split('?')[0]
    
    return dict(canonical_url=canonical)
```

### Template Usage
```html
<!-- In base.html or equivalent -->
<link rel="canonical" href="{{ canonical_url }}">
<meta property="og:url" content="{{ canonical_url }}">
```

### URL Redirects (Flask)
```python
@app.route('/old-url')
def redirect_old_url():
    return redirect(url_for('new_url_function'), code=301)
```

---

## Expected Timeline

- **Immediate:** Redirects and robots.txt fixes take effect
- **1-2 weeks:** Google re-crawls and updates indexing
- **2-4 weeks:** Duplicate content issues should resolve
- **Ongoing:** Monitor Search Console for improvements

---

## Key Takeaways

1. **Canonical tags are critical** - Always use clean, normalized URLs without query parameters
2. **Redirects prevent 404s** - Always redirect old URLs to new ones when changing URL structure
3. **robots.txt must match routes** - Keep it synchronized with your actual routes
4. **Dynamic sitemaps are better** - They automatically stay up-to-date
5. **Monitor regularly** - Check Google Search Console weekly for indexing issues

---

## Common Google Search Console Error Messages

| Error Message | Likely Cause | Solution |
|--------------|--------------|----------|
| "Page with redirect" | Old URLs redirecting | Add proper 301 redirects |
| "Not found (404)" | Broken links or wrong URLs | Fix URLs in robots.txt, add redirects |
| "Duplicate, Google chose different canonical" | Canonical tag issues | Fix canonical tags to use clean URLs |
| "Crawled - currently not indexed" | Low quality or duplicate content | Improve content, fix canonical tags |
| "Excluded by 'noindex' tag" | Pages have noindex meta tag | Remove noindex if page should be indexed |

---

## Notes

- Always use 301 (permanent) redirects, not 302 (temporary)
- Canonical URLs should be absolute (include full domain)
- Query parameters in URLs create duplicate content issues
- Monitor Google Search Console regularly for new issues
- Use "Request Indexing" feature for important pages after fixes

---

**Last updated:** May 2026 (migrated checklist; apply items per site as needed)
