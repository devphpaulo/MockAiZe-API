window.addEventListener('load', function () {
  window.ui = SwaggerUIBundle({
    url: '/openapi.json',
    dom_id: '#swagger-ui',
    presets: [SwaggerUIBundle.presets.apis],
    layout: 'BaseLayout',
    deepLinking: true,
    filter: true,
    displayRequestDuration: true,
    docExpansion: 'list',
    supportedSubmitMethods: ['get', 'post'],
    validatorUrl: null,
    persistAuthorization: false,
    queryConfigEnabled: false
  });
});
