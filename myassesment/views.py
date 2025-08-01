from django.http import HttpResponse

def Home(request):
        return HttpResponse("Hello word ....... its Home Page")

def About(request):
        return HttpResponse("Hello word ....... its About Page")

def Contact(request):
        return HttpResponse("Hello word ....... its Contact Page")