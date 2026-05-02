# Global website development rules (Cursor settings)

Paste into **Cursor → Settings → Rules** (or your team’s global rules) for expectations that apply across **all** repositories—not only this template.

For **this** containerized starter, use together with:

- [`website_guidelines.md`](../website_guidelines.md) in the project root  
- [`.cursorrules`](../.cursorrules) for project-specific AI rules  

**Note:** This template uses idempotent DDL in `setup_database.py` (`init_db()`), not a checked-in `database_schema.sql`. Keep that in mind when the bullets below mention schema files—they still apply to older repos that use SQL migrations.

---

## Core principles

- Multi-tenant architecture with `tenant_id` foreign keys  
- Security-first: rate limiting, CSRF protection, input validation  
- Consistent database naming (`pc_`, `fc_`, `custom_` prefixes) where you use prefixes  
- Flask-Login patterns with `User(UserMixin)`  
- Professional frontend with theme support  
- Comprehensive error handling and logging  

## Code standards

- Include license headers in files you add or materially change  
- Use parameterized database queries to prevent SQL injection  
- Implement proper session management with `SESSION_COOKIE_HTTPONLY`  
- Follow the established file organization structure  
- Use consistent API response formats (success/error with timestamps)  

## Frontend standards

- Use Bootstrap 5 with custom CSS variables for theming  
- Implement dark/light theme switching  
- Include proper SEO meta tags and schema markup  
- Create responsive designs with a mobile-first approach  
- Use consistent email template structure with inline CSS  

## Database standards

- All tables should have: `id`, `tenant_id`, `created_at`, `updated_at` (where multi-tenant)  
- Use proper foreign key constraints with sensible `ON DELETE` behavior  
- Follow naming conventions: `snake_case` with descriptive prefixes  
- For apps that still use `database_schema.sql`: never rewrite deployed history; add migrations or guarded `ALTER`s  
- Use migration scripts or guarded in-code DDL for production changes  

## Security requirements

- Rate limit sensitive API endpoints and forms  
- Implement CSRF protection on all state-changing operations  
- Use bleach for rich text sanitization where users supply HTML  
- Log security events  
- Validate all form inputs server-side  

## File organization (classic layout)

Many older Flask repos follow:

```
project/
├── app.py
├── database.py
├── security.py
├── cache_manager.py
├── setup_database.py
├── requirements.txt
├── .env.example
├── database_schema.sql
├── deployment_items/
└── app/
    └── templates/
```

## Template standards

- Include license headers in templates you add or materially change  
- Use consistent block structure (title, content, etc.)  
- Implement proper theme support with `data-theme` attributes  
- Include schema.org markup in footers where appropriate  
- Use consistent error page structure  

## Email standards

- Use inline CSS for email compatibility  
- Follow consistent styling patterns  
- Implement proper security notifications  
- Use professional email templates  

## Static assets

- Include favicon, robots.txt, sitemap (static or dynamic)  
- Provide social preview images where relevant  
- Optimize images for web performance  

## Error handling

- Create custom error pages (404, 500, 403)  
- Implement proper error logging  
- Use user-friendly error messages  

## API design

- Use consistent JSON response format  
- Include timestamps in responses where appropriate  
- Implement proper HTTP status codes  
- Use RESTful endpoint naming conventions  

## Logging

- Use structured logging with proper levels  
- Log security events and important user actions  
- Include timestamps and context information  

## Testing requirements

- Test forms with edge cases  
- Verify responsive design on multiple viewports  
- Test theme switching  
- Validate email templates  
- Check SEO meta tags and schema markup  

## Code review checklist

- [ ] Security measures implemented  
- [ ] Database queries use parameters  
- [ ] Error handling is comprehensive  
- [ ] UI is responsive and accessible  
- [ ] Performance optimizations applied  
- [ ] Debug code removed  
- [ ] Documentation updated  
- [ ] Email templates tested  
- [ ] Theme switching works  
- [ ] SEO meta tags present  
- [ ] Schema markup included  
- [ ] Static assets optimized  

## Quick reference

- For detailed patterns in **this** template: `website_guidelines.md`  
- For project AI rules in **this** template: `.cursorrules`  
- Follow established code examples in each repository  
- Keep new work consistent with your existing production sites  
- Prioritize security and user experience  
- Test thoroughly before deployment  
