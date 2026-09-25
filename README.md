# Amiri Insurance Website

Flask app for the public site and admin CRM. Local development uses `python app.py`. Production uses gunicorn + nginx + PostgreSQL. Full steps are in [DEPLOY.md](DEPLOY.md).

```bash
py -3 -m pip install -r requirements.txt
copy .env.example .env
py -3 app.py
```

Open http://localhost:5000

```bash
# production-style local run
gunicorn -c gunicorn.conf.py wsgi:app
```

Admin login notes are in `ADMIN_README.md`.

---

# Website Improvements

## Overview
This document outlines the comprehensive improvements made to the Amiri Insurance Agency website to enhance SEO, performance, accessibility, security, and user experience.

## Improvements Made

### 1. SEO Enhancements
- **Meta Tags**: Added comprehensive meta tags including keywords, descriptions, and author information
- **Open Graph Protocol**: Implemented Facebook and Twitter sharing meta tags
- **Canonical URLs**: Added canonical links to prevent duplicate content issues
- **Structured Data**: Added JSON-LD schema markup for better search engine understanding
- **Sitemap**: Created `sitemap.xml` for better search engine crawling
- **Robots.txt**: Added `robots.txt` file to guide search engine crawlers

### 2. Performance Optimizations
- **Lazy Loading**: Added `loading="lazy"` attribute to images for better page load performance
- **CSS Optimization**: Created `improvements.css` for centralized styling improvements
- **JavaScript Optimization**: Enhanced `main.js` and created `improvements.js` for better functionality
- **Resource Preloading**: Added preconnect links for external resources

### 3. Accessibility Improvements
- **Skip Links**: Added skip-to-main-content links for keyboard navigation
- **ARIA Labels**: Added proper ARIA labels to interactive elements
- **Focus Management**: Improved focus styles and keyboard navigation
- **Semantic HTML**: Enhanced HTML structure with proper semantic elements
- **Color Contrast**: Improved color contrast for better readability

### 4. Security Enhancements
- **API Key Removal**: Removed exposed Mailchimp API key from client-side code
- **Form Validation**: Added client-side form validation with proper error handling
- **Error Handling**: Implemented proper error messages and loading states

### 5. User Experience Improvements
- **Mobile Responsiveness**: Enhanced mobile layout and typography
- **Form Handling**: Improved appointment and newsletter forms with better UX
- **Loading States**: Added loading animations and success/error messages
- **Hover Effects**: Enhanced interactive elements with smooth transitions

### 6. Content Enhancements
- **Blog Improvements**: Completely redesigned blog page with modern layout
- **Blog Listing**: Created new `blog-listing.html` page for multiple blog posts
- **Social Sharing**: Added social media sharing buttons to blog posts
- **Related Content**: Added sidebar with related services and recent posts
- **Tags and Categories**: Implemented blog tagging and categorization system

## New Files Created

### CSS Files
- `css/improvements.css` - Centralized improvements and blog-specific styles

### JavaScript Files
- `js/improvements.js` - Enhanced functionality for forms, accessibility, and performance

### SEO Files
- `robots.txt` - Search engine crawling instructions
- `sitemap.xml` - XML sitemap for search engines
- `structured-data.json` - JSON-LD schema markup

### Blog Pages
- `blog-listing.html` - New blog listing page with multiple posts and sidebar

### Documentation
- `README.md` - This comprehensive documentation file

## Technical Specifications

### SEO Implementation
```html
<!-- Meta Tags -->
<meta name="keywords" content="Amiri Insurance, Kenya insurance, health insurance, vehicle insurance, property insurance, life insurance, business insurance, money insurance, WIBA insurance, Nairobi insurance agency" />
<meta name="description" content="Amiri Insurance Agency - Kenya's trusted insurance partner offering comprehensive health, vehicle, property, and business insurance solutions." />
<meta name="author" content="Amiri Insurance Agency" />
<meta name="robots" content="index, follow" />

<!-- Open Graph -->
<meta property="og:type" content="website" />
<meta property="og:url" content="https://amiriinsuranceagency.com/" />
<meta property="og:title" content="Amiri Insurance - Kenya's Trusted Insurance Partner" />
<meta property="og:description" content="Comprehensive insurance solutions for health, vehicle, property, and business in Kenya." />
<meta property="og:image" content="https://amiriinsuranceagency.com/img/icon/icon-02-primary.png" />

<!-- Twitter Cards -->
<meta property="twitter:card" content="summary_large_image" />
<meta property="twitter:url" content="https://amiriinsuranceagency.com/" />
<meta property="twitter:title" content="Amiri Insurance - Kenya's Trusted Insurance Partner" />
<meta property="twitter:description" content="Comprehensive insurance solutions for health, vehicle, property, and business in Kenya." />
<meta property="twitter:image" content="https://amiriinsuranceagency.com/img/icon/icon-02-primary.png" />
```

### Accessibility Features
```html
<!-- Skip Link -->
<a href="#main-content" class="skip-link">Skip to main content</a>

<!-- Semantic Structure -->
<main id="main-content">
    <!-- Page content -->
</main>

<!-- ARIA Labels -->
<button type="button" class="navbar-toggler" data-bs-toggle="collapse" data-bs-target="#navbarCollapse" aria-label="Toggle navigation">
```

### Blog Improvements
- **Modern Layout**: Responsive grid layout with featured posts
- **Social Sharing**: Facebook, Twitter, LinkedIn, and email sharing
- **Related Content**: Sidebar with categories, recent posts, and tags
- **Search Functionality**: Blog search with proper form handling
- **Pagination**: Clean pagination for multiple blog posts
- **Author Information**: Author cards with company information
- **Call-to-Action**: Strategic CTAs for insurance services

## Implementation Notes

### Security Considerations
- Removed client-side API keys and replaced with server-side recommendations
- Implemented proper form validation and error handling
- Added loading states to prevent multiple submissions

### Performance Optimizations
- Lazy loading for images to improve initial page load
- Debounced scroll events for better performance
- Optimized CSS and JavaScript loading

### Accessibility Compliance
- WCAG 2.1 AA compliance with proper focus management
- Screen reader friendly with proper ARIA labels
- Keyboard navigation support throughout the site

## Maintenance Recommendations

### Regular Updates
1. **Content Updates**: Keep blog content fresh and relevant
2. **SEO Monitoring**: Regularly check search engine rankings
3. **Performance Testing**: Monitor page load speeds
4. **Security Audits**: Regular security reviews and updates

### Future Enhancements
1. **CMS Integration**: Consider implementing a content management system
2. **Analytics**: Add Google Analytics for better user insights
3. **Chat Support**: Implement live chat functionality
4. **Online Quotes**: Add online insurance quote calculator
5. **Customer Portal**: Create customer account management system

### Blog Content Strategy
1. **Regular Posts**: Publish weekly insurance tips and industry news
2. **SEO Content**: Create content targeting relevant keywords
3. **Social Media**: Share blog posts on social platforms
4. **Email Marketing**: Include blog content in newsletter campaigns

## File Structure
```
amiri/
├── index.html (Updated with SEO and accessibility)
├── blog.html (Completely redesigned)
├── blog-listing.html (New blog listing page)
├── css/
│   ├── improvements.css (New comprehensive styles)
│   ├── style.css (Existing)
│   └── styles2.css (Existing)
├── js/
│   ├── improvements.js (New enhanced functionality)
│   └── main.js (Updated with security fixes)
├── robots.txt (New SEO file)
├── sitemap.xml (New SEO file)
├── structured-data.json (New SEO file)
└── README.md (This documentation)
```

## Browser Compatibility
- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+
- Mobile browsers (iOS Safari, Chrome Mobile)

## Performance Metrics
- **Page Load Speed**: Optimized for under 3 seconds
- **Mobile Performance**: Responsive design with mobile-first approach
- **SEO Score**: Improved meta tags and structured data
- **Accessibility Score**: WCAG 2.1 AA compliant

## Contact Information
For technical support or questions about these improvements, contact:
- **Website**: https://amiriinsuranceagency.com
- **Email**: info@amiriinsuranceagency.com
- **Phone**: +254 713193568

---

*Last Updated: October 10, 2024*
*Version: 2.0* 